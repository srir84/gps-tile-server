/* server.c: the web server declared in server.h (DESIGN §7, §9.2). */
#define _POSIX_C_SOURCE 200809L /* sockets, pthreads, strncasecmp with -std=c11 */

#include "server.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "geo.h"
#include "render.h"

int server_valid_id(const char *id)
{
    size_t length = strlen(id);
    return length >= 1 && length <= SERVER_MAX_ID &&
           strspn(id, "abcdefghijklmnopqrstuvwxyz0123456789-_") == length;
}

/* Parses 1 to 9 digits from text up to `end`. Returns 0 if ok. */
static int parse_number(const char *text, const char *end, uint32_t *out)
{
    size_t length = (size_t)(end - text);
    if (length == 0 || length > 9)
        return -1;
    uint32_t value = 0;
    for (const char *p = text; p < end; p++) {
        if (*p < '0' || *p > '9')
            return -1;
        value = value * 10 + (uint32_t)(*p - '0');
    }
    *out = value;
    return 0;
}

static const struct dataset *find_dataset(const char *id, size_t length, const struct dataset *datasets, size_t count)
{
    for (size_t i = 0; i < count; i++) {
        if (strlen(datasets[i].id) == length && memcmp(datasets[i].id, id, length) == 0)
            return &datasets[i];
    }
    return NULL;
}

static struct route error_route(enum route_kind kind, const char *message)
{
    return (struct route){.kind = kind, .message = message};
}

static int hex_digit(char c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

/* The value of `name` in a query (a=1&b=2), %XX decoded into out[size]. Returns 1 if found, 0 if not, and
 * QUERY_TWICE, QUERY_TOO_LONG or QUERY_BAD_ESCAPE (negative) if it is there twice, too long, or has a bad %. */
enum { QUERY_TWICE = -1, QUERY_TOO_LONG = -2, QUERY_BAD_ESCAPE = -3 };
static int query_value(const char *query, const char *name, char *out, size_t size)
{
    int found = 0;
    size_t name_length = strlen(name);
    for (const char *p = query; p != NULL && *p != '\0'; p = strchr(p, '&'), p = p != NULL ? p + 1 : NULL) {
        size_t length = strcspn(p, "&");
        if (length <= name_length || p[name_length] != '=' || memcmp(p, name, name_length) != 0)
            continue;
        if (found++)
            return QUERY_TWICE;
        size_t n = 0;
        for (const char *v = p + name_length + 1; v < p + length; v++) {
            int c = (unsigned char)*v;
            if (c == '%') { /* scripts may send a comma as %2C */
                int high = v + 2 < p + length ? hex_digit(v[1]) : -1, low = high >= 0 ? hex_digit(v[2]) : -1;
                if (low < 0)
                    return QUERY_BAD_ESCAPE;
                c = high * 16 + low;
                v += 2;
            }
            if (c == '\0')
                return QUERY_BAD_ESCAPE;
            if (n + 1 >= size)
                return QUERY_TOO_LONG;
            out[n++] = (char)c;
        }
        out[n] = '\0';
    }
    return found;
}

/* 1 if every parameter in the query is one of the `allowed` names (a NULL-terminated list). */
static int known_parameters(const char *query, const char *const *allowed)
{
    for (const char *p = query; p != NULL && *p != '\0'; p = strchr(p, '&'), p = p != NULL ? p + 1 : NULL) {
        size_t length = strcspn(p, "=&");
        int known = 0;
        for (const char *const *a = allowed; *a != NULL; a++)
            known |= strlen(*a) == length && memcmp(*a, p, length) == 0;
        if (!known)
            return 0;
    }
    return 1;
}

/* /api/datasets/{id}/count and /export.csv: the box (DESIGN §9.2), and for an export the row limit. */
static struct route box_route(enum route_kind kind, const struct dataset *d, const char *query)
{
    static const char *const count_names[] = {"bbox", NULL}, *const export_names[] = {"bbox", "limit", NULL};
    if (!known_parameters(query, kind == ROUTE_COUNT ? count_names : export_names))
        return error_route(ROUTE_BAD_REQUEST, kind == ROUTE_COUNT ? "unknown parameter: count takes bbox"
                                                                  : "unknown parameter: export takes bbox and limit");
    char text[128];
    const char *why = "bbox=west,south,east,north is required";
    struct route r = {.kind = kind, .dataset = d, .limit = SERVER_MAX_EXPORT};
    int found = query_value(query, "bbox", text, sizeof text);
    if (found < 0)
        return error_route(ROUTE_BAD_REQUEST, found == QUERY_TWICE      ? "bbox is given more than once"
                                              : found == QUERY_TOO_LONG ? "bbox is too long (127 characters at most)"
                                                                        : "bbox has a bad %-escape");
    if (found == 0 || area_parse_bbox(text, &r.box, &why) != 0)
        return error_route(ROUTE_BAD_REQUEST, why);
    int has_limit = query_value(query, "limit", text, sizeof text);
    uint32_t limit;
    if (has_limit == QUERY_TWICE)
        return error_route(ROUTE_BAD_REQUEST, "limit is given more than once");
    if (has_limit != 0 && (has_limit < 0 || parse_number(text, text + strlen(text), &limit) != 0 || limit == 0 ||
                           limit > SERVER_MAX_EXPORT))
        return error_route(ROUTE_BAD_REQUEST, "limit must be a whole number from 1 to 1000000");
    if (has_limit > 0)
        r.limit = limit;
    return r;
}

struct route server_route(const char *method, const char *target, const struct dataset *datasets, size_t count)
{
    if (strcmp(method, "GET") != 0 && strcmp(method, "HEAD") != 0)
        return error_route(ROUTE_BAD_METHOD, "only GET and HEAD are supported");
    size_t length = strcspn(target, "?");
    const char *end = target + length, *query = target[length] == '?' ? target + length + 1 : "";
    static const char api[] = "/api/datasets", tiles[] = "/tiles/";
    for (size_t i = 0; i < www_file_count; i++) {
        if (strlen(www_files[i].path) == length && memcmp(www_files[i].path, target, length) == 0)
            return (struct route){.kind = ROUTE_FILE, .file = &www_files[i]};
    }
    if (length == sizeof api - 1 && memcmp(target, api, length) == 0)
        return (struct route){.kind = ROUTE_DATASETS};
    if (length > sizeof api && memcmp(target, api, sizeof api - 1) == 0 && target[sizeof api - 1] == '/') {
        /* /api/datasets/{id}, then nothing, /count or /export.csv */
        const char *id = target + sizeof api, *slash = memchr(id, '/', (size_t)(end - id));
        const char *id_end = slash != NULL ? slash : end;
        size_t rest = (size_t)(end - id_end);
        enum route_kind kind = rest == 0                                              ? ROUTE_DATASET
                               : rest == 6 && memcmp(id_end, "/count", 6) == 0        ? ROUTE_COUNT
                               : rest == 11 && memcmp(id_end, "/export.csv", 11) == 0 ? ROUTE_EXPORT
                                                                                      : ROUTE_NOT_FOUND;
        if (kind == ROUTE_NOT_FOUND)
            return error_route(ROUTE_NOT_FOUND, "not found");
        const struct dataset *d = find_dataset(id, (size_t)(id_end - id), datasets, count);
        if (d == NULL)
            return error_route(ROUTE_NOT_FOUND, "unknown dataset");
        return kind == ROUTE_DATASET ? (struct route){.kind = ROUTE_DATASET, .dataset = d} : box_route(kind, d, query);
    }
    if (length > sizeof tiles - 1 && memcmp(target, tiles, sizeof tiles - 1) == 0) {
        /* /tiles/{id}/{z}/{x}/{y}.png */
        const char *part[4], *p = target + sizeof tiles - 1;
        for (int k = 0; k < 4; k++) {
            part[k] = p;
            p = memchr(p, '/', (size_t)(end - p));
            if (k < 3 && p == NULL)
                return error_route(ROUTE_NOT_FOUND, "not found");
            if (k < 3)
                p++;
            else if (p != NULL)
                return error_route(ROUTE_NOT_FOUND, "not found");
        }
        if (end - part[3] < 4 || memcmp(end - 4, ".png", 4) != 0)
            return error_route(ROUTE_NOT_FOUND, "not found");
        const struct dataset *d = find_dataset(part[0], (size_t)(part[1] - 1 - part[0]), datasets, count);
        if (d == NULL)
            return error_route(ROUTE_NOT_FOUND, "unknown dataset");
        uint32_t zoom, x, y;
        if (parse_number(part[1], part[2] - 1, &zoom) != 0 || parse_number(part[2], part[3] - 1, &x) != 0 ||
            parse_number(part[3], end - 4, &y) != 0)
            return error_route(ROUTE_BAD_REQUEST, "bad tile address: zoom, x and y must be whole numbers");
        if (zoom > GEO_MAX_ZOOM || x >> zoom != 0 || y >> zoom != 0)
            return error_route(ROUTE_NOT_FOUND, "no such tile");
        return (struct route){.kind = ROUTE_TILE, .dataset = d, .zoom = zoom, .x = x, .y = y};
    }
    return error_route(ROUTE_NOT_FOUND, "not found");
}

/* ---- Responses ---- */

/* One connection: its (non-blocking) socket, whether the answer has a body (not for HEAD), whether the client
 * speaks HTTP/1.1 (chunked answers) or 1.0, and the time its answer must be sent by (a client that stops
 * reading can't hold a connection slot for long). For a long answer (an export) `idle` is set: every write
 * that goes through moves the deadline to `idle` seconds later, so a client that keeps reading is served to
 * the end and one that stops for that long is let go. */
struct client {
    int fd;
    int body;
    int http11;
    int idle;
    struct timespec write_deadline;
};

/* Milliseconds left until `deadline` (CLOCK_MONOTONIC), at least 0. */
static int ms_left(const struct timespec *deadline)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    long long ms = (long long)(deadline->tv_sec - now.tv_sec) * 1000 + (deadline->tv_nsec - now.tv_nsec) / 1000000;
    return ms < 0 ? 0 : ms > 3600000 ? 3600000 : (int)ms;
}

static struct timespec seconds_from_now(int seconds)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    t.tv_sec += seconds;
    return t;
}

/* Waits for the socket to be ready (POLLIN or POLLOUT) until the deadline. Returns 1 when ready, 0 when the
 * deadline passed, -1 on error. */
static int wait_for(int fd, short events, const struct timespec *deadline)
{
    for (;;) {
        struct pollfd p = {fd, events, 0};
        int ready = poll(&p, 1, ms_left(deadline));
        if (ready < 0 && errno == EINTR)
            continue;
        return ready < 0 ? -1 : ready > 0;
    }
}

static int send_all(struct client *c, const void *data, size_t size)
{
    const char *p = data;
    while (size > 0) {
        if (wait_for(c->fd, POLLOUT, &c->write_deadline) != 1)
            return -1; /* the client stopped reading: give the slot back */
        ssize_t sent = write(c->fd, p, size);
        if (sent < 0 && (errno == EINTR || errno == EAGAIN))
            continue;
        if (sent <= 0)
            return -1; /* the client went away */
        p += sent;
        size -= (size_t)sent;
        if (c->idle > 0) /* the client is reading: another `idle` seconds */
            c->write_deadline = seconds_from_now(c->idle);
    }
    return 0;
}

static void respond(struct client *c, int status, const char *reason, const char *type, const char *extra,
                    const void *body, size_t size)
{
    char head[1024]; /* the longest, the page with its Content-Security-Policy, is about 450 bytes */
    int n = snprintf(head, sizeof head,
                     "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\n"
                     "X-Content-Type-Options: nosniff\r\nConnection: close\r\n%s\r\n",
                     status, reason, type, size, extra);
    if (n > 0 && (size_t)n < sizeof head && send_all(c, head, (size_t)n) == 0 && size > 0 && c->body)
        send_all(c, body, size);
}

static void respond_error(struct client *c, int status, const char *message)
{
    static const struct {
        int status;
        const char *reason;
    } reasons[] = {{400, "Bad Request"}, {403, "Forbidden"},      {404, "Not Found"},
                   {405, "Method Not Allowed"}, {408, "Request Timeout"}, {414, "URI Too Long"},
                   {431, "Request Header Fields Too Large"}, {500, "Internal Server Error"}};
    const char *reason = "Error";
    for (size_t i = 0; i < sizeof reasons / sizeof reasons[0]; i++) {
        if (reasons[i].status == status)
            reason = reasons[i].reason;
    }
    char body[160];
    int n = snprintf(body, sizeof body, "%d %s\n", status, message);
    size_t length = n < 0 ? 0 : (size_t)n < sizeof body ? (size_t)n : sizeof body - 1; /* never past the buffer */
    respond(c, status, reason, "text/plain; charset=utf-8", status == 405 ? "Allow: GET, HEAD\r\n" : "", body, length);
}

/* A growing text buffer for JSON. On out of memory it stops growing and remembers the failure. */
struct text {
    char *data;
    size_t length, capacity;
    int failed;
};

static void add(struct text *t, const char *format, ...)
{
    for (int attempt = 0; attempt < 2 && !t->failed; attempt++) {
        va_list args;
        va_start(args, format);
        int n = vsnprintf(t->data == NULL ? NULL : t->data + t->length, t->capacity - t->length, format, args);
        va_end(args);
        if (n < 0) {
            t->failed = 1;
        } else if ((size_t)n < t->capacity - t->length) {
            t->length += (size_t)n;
            return;
        } else {
            size_t capacity = (t->capacity + (size_t)n + 1) * 2;
            char *data = realloc(t->data, capacity);
            if (data == NULL)
                t->failed = 1;
            else {
                t->data = data;
                t->capacity = capacity;
            }
        }
    }
}

static void add_box(struct text *t, const char *name, uint64_t count, uint32_t min_x, uint32_t min_y, uint32_t max_x,
                    uint32_t max_y)
{
    if (count == 0)
        add(t, "\"%s\":null", name);
    else
        add(t, "\"%s\":[%.6f,%.6f,%.6f,%.6f]", name, geo_lon(min_x), geo_lat(max_y), geo_lon(max_x), geo_lat(min_y));
}

/* One dataset as a JSON object: id, points, bounds and view (west, south, east, north, or null when
 * empty), max zoom and the densest pixel per zoom (the color scale). */
static void add_dataset(struct text *t, const struct dataset *d)
{
    const struct build_header *h = &d->file.header;
    add(t, "{\"id\":\"%s\",\"points\":%" PRIu64 ",", d->id, h->count);
    add_box(t, "bounds", h->count, h->min_x, h->min_y, h->max_x, h->max_y);
    add(t, ",");
    add_box(t, "view", h->count, h->view_min_x, h->view_min_y, h->view_max_x, h->view_max_y);
    add(t, ",\"max_zoom\":%d,\"max_pixel\":[", GEO_MAX_ZOOM);
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        add(t, "%" PRIu64 "%s", h->max_pixel_count[z], z < GEO_MAX_ZOOM ? "," : "]}");
}

static void respond_json(struct client *c, struct text *t)
{
    if (t->failed)
        respond_error(c, 500, "out of memory");
    else
        respond(c, 200, "OK", "application/json", "", t->data, t->length);
    free(t->data);
}

/* An export's CSV, sent in chunks (HTTP/1.1 chunked encoding) as the points are found: a large export needs
 * little memory, and a download cut short can be told from a whole one (no final empty chunk). */
struct csv {
    struct client *client;
    const struct area_box *box;
    int chunked; /* HTTP/1.1: chunks; HTTP/1.0: the rows as they are, and the closed connection ends the file */
    int failed; /* the client went away or stopped reading: stop looking for points */
    size_t used;
    char data[65536];
};

static int flush_csv(struct csv *c)
{
    char size[24];
    int n = snprintf(size, sizeof size, "%zx\r\n", c->used);
    if (c->used > 0 && ((c->chunked && send_all(c->client, size, (size_t)n) != 0) ||
                        send_all(c->client, c->data, c->used) != 0 || (c->chunked && send_all(c->client, "\r\n", 2) != 0)))
        c->failed = 1;
    c->used = 0;
    return c->failed;
}

/* Writes degrees v, kept within [low, high], with 9 decimals, or as many more (up to 30) as it takes to
 * stay within [low, high] and in world unit `unit` when read back as a point by `to_unit` (a longitude
 * rounded up to 180 is -180). The clamped v itself qualifies, so enough decimals always do; never an
 * exponent. Returns the length. */
static int put_degrees(char *out, size_t size, double v, double low, double high, uint32_t unit,
                       uint32_t (*to_unit)(double))
{
    v = v < low ? low : v > high ? high : v;
    int n = 0;
    for (int decimals = 9; decimals <= 30; decimals++) {
        n = snprintf(out, size, "%.*f", decimals, v);
        double back = strtod(out, NULL);
        if (back >= low && back <= high && to_unit(back) == unit)
            break;
    }
    return n;
}

/* One row: the middle of the point's world unit (read back, exactly that unit), kept inside the box's
 * degrees. A box edge lies in the unit of the points on it, so a row moved onto the edge still reads back
 * as its unit. Not at longitude ±180: there the middle is already inside, and 180 would read back as -180. */
static int add_row(uint32_t x, uint32_t y, void *context)
{
    struct csv *c = context;
    const struct area_box *b = c->box;
    if (sizeof c->data - c->used < 96 && flush_csv(c) != 0)
        return 1;
    char *row = c->data + c->used;
    size_t room = sizeof c->data - c->used;
    double west = b->west == 180.0 ? -180.0 : b->west;
    int n = put_degrees(row, room, geo_lon(x + 0.5), west, b->east, x, geo_world_x);
    row[n] = ',';
    n += 1 + put_degrees(row + n + 1, room - (size_t)n - 1, geo_lat(y + 0.5), b->south, b->north, y, geo_world_y);
    row[n] = '\n';
    c->used += (size_t)n + 1;
    return 0;
}

/* GET /api/datasets/{id}/export.csv: `lon,lat`, then one row per point in the box, in file order, at most
 * r->limit rows. A row is the middle of the point's world unit with 9 decimals: read back (an import, a
 * box) it is exactly that unit, and never outside the map. X-Total-Points says how
 * many are in the box, X-Rows how many rows follow. HEAD: the headers only. Chunked for HTTP/1.1; for
 * HTTP/1.0 (no chunks) the rows as they are, ended by closing the connection. */
static void export_csv(struct client *client, const struct route *r, int timeout)
{
    struct csv *c = malloc(sizeof *c);
    if (c == NULL) {
        respond_error(client, 500, "out of memory");
        return;
    }
    uint64_t total = area_count(&r->dataset->file, &r->box);
    uint64_t rows = total < r->limit ? total : r->limit;
    /* A client that keeps reading may take its time; one that stops for 3 × timeout seconds is let go. (On
     * macOS a write goes through only after the client has read about one socket buffer, 0.5–0.7 MB, so
     * with the default timeout a reader needs about 23 KB/s: one row-by-row script's pace.) */
    client->idle = 3 * timeout;
    client->write_deadline = seconds_from_now(client->idle);
    char head[512];
    int n = snprintf(head, sizeof head,
                     "HTTP/1.1 200 OK\r\nContent-Type: text/csv; charset=utf-8\r\n"
                     "Content-Disposition: attachment; filename=\"%s-export.csv\"\r\n"
                     "X-Total-Points: %" PRIu64 "\r\nX-Rows: %" PRIu64 "\r\n%s"
                     "X-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n",
                     r->dataset->id, total, rows, client->http11 ? "Transfer-Encoding: chunked\r\n" : "");
    *c = (struct csv){.client = client, .box = &r->box, .chunked = client->http11};
    if (n > 0 && (size_t)n < sizeof head && send_all(client, head, (size_t)n) == 0 && client->body) {
        memcpy(c->data, "lon,lat\n", 8);
        c->used = 8;
        area_points(&r->dataset->file, &r->box, rows, add_row, c);
        if (flush_csv(c) == 0 && c->chunked)
            send_all(client, "0\r\n\r\n", 5);
    }
    free(c);
}

/* ---- Connections ---- */

struct server {
    const struct dataset *datasets;
    size_t count;
    int timeout; /* seconds a client has to send its whole request */
};

struct connection {
    int fd;
    const struct server *server;
};

static pthread_mutex_t slots_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t slot_free = PTHREAD_COND_INITIALIZER;
static int connections;

/* 1 if a Host value is safe to answer: localhost or an IP address, with or without a port. A page from
 * another site that points its own name at this machine (DNS rebinding) sends that name: refused. */
static int safe_host(const char *value, size_t length)
{
    char name[64];
    if (length == 0 || length >= sizeof name)
        return 0;
    memcpy(name, value, length);
    name[length] = '\0';
    char *port = name[0] == '[' ? strchr(name, ']') : strchr(name, ':');
    if (port != NULL && name[0] == '[')
        port++; /* after "[::1]" */
    if (port != NULL && *port != '\0') {
        if (*port != ':' || port[1] == '\0' || strspn(port + 1, "0123456789") != strlen(port + 1) || strlen(port + 1) > 5)
            return 0;
        *port = '\0';
    }
    struct in_addr address;
    return strcasecmp(name, "localhost") == 0 || strcmp(name, "[::1]") == 0 || inet_pton(AF_INET, name, &address) == 1;
}

/* The request head after the checks HTTP/1.1 asks for (RFC 9112): "METHOD SP TARGET SP HTTP/1.0|1.1" and
 * header lines "Name: value" (the method and names tokens, no control characters, lines ended by CR LF), exactly
 * one Host for HTTP/1.1. */
struct request {
    char *method, *target;
    int http11; /* HTTP/1.1, else 1.0 */
    const char *host; /* NULL if none (HTTP/1.0) */
    size_t host_length;
};

/* 1 if text[0..length) is a token (RFC 9110 §5.6.2), what a method or a header name must be. */
static int is_token(const char *text, size_t length)
{
    for (size_t i = 0; i < length; i++) {
        char c = text[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
              (c != '\0' && strchr("!#$%&'*+-.^_`|~", c) != NULL)))
            return 0;
    }
    return length > 0;
}

/* 1 if text[0..length) has no control character but tab (RFC 9110 §5.5; bytes from 0x80 are allowed). */
static int no_controls(const char *text, size_t length)
{
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)text[i];
        if ((c < 0x20 && c != '\t') || c == 0x7f)
            return 0;
    }
    return 1;
}

/* Parses the head in place (it ends with an empty line). Returns NULL, or why it is a bad request. */
static const char *parse_head(char *head, struct request *r)
{
    char *line_end = strstr(head, "\r\n");
    char *space = strchr(head, ' ');
    char *space2 = space != NULL && space < line_end ? strchr(space + 1, ' ') : NULL;
    if (space == NULL || space2 == NULL || space2 > line_end || !is_token(head, (size_t)(space - head)) ||
        space[1] != '/' || !no_controls(space + 1, (size_t)(space2 - space - 1)) ||
        line_end - (space2 + 1) != 8 || (strncmp(space2 + 1, "HTTP/1.0", 8) != 0 && strncmp(space2 + 1, "HTTP/1.1", 8) != 0))
        return "bad request line";
    int http11 = r->http11 = space2[8] == '1';
    *space = '\0';
    *space2 = '\0';
    r->method = head;
    r->target = space + 1;
    r->host = NULL;
    int hosts = 0;
    for (char *line = line_end + 2; strncmp(line, "\r\n", 2) != 0; line = strstr(line, "\r\n") + 2) {
        size_t length = strcspn(line, "\r\n"), name = strcspn(line, ":\r\n");
        /* A name that is a token, a value without control characters, and the line ended by CR LF (a bare
         * CR or LF would end it for some other HTTP reader, which could then see another header). */
        if (name >= length || !is_token(line, name) || !no_controls(line + name + 1, length - name - 1) ||
            line[length] != '\r' || line[length + 1] != '\n')
            return "bad header line";
        if (name == 4 && strncasecmp(line, "Host", 4) == 0) {
            const char *value = line + 5 + strspn(line + 5, " \t");
            size_t value_length = (size_t)(line + length - value);
            while (value_length > 0 && (value[value_length - 1] == ' ' || value[value_length - 1] == '\t'))
                value_length--;
            r->host = value;
            r->host_length = value_length;
            hosts++;
        }
    }
    if (hosts > 1 || (http11 && hosts == 0))
        return "HTTP/1.1 needs exactly one Host header";
    return NULL;
}

static void handle(struct client *c, const struct server *s, char *head)
{
    c->body = strncmp(head, "HEAD ", 5) != 0; /* known before any check, so even a refused HEAD has no body */
    struct request req;
    const char *bad = parse_head(head, &req);
    if (bad != NULL) {
        respond_error(c, 400, bad);
        return;
    }
    c->http11 = req.http11;
    if (req.host != NULL && !safe_host(req.host, req.host_length)) {
        respond_error(c, 403, "this server only answers requests for localhost or an IP address");
        return;
    }
    struct route r = server_route(req.method, req.target, s->datasets, s->count);
    switch (r.kind) {
    case ROUTE_FILE:
        /* The page may load only this server's files and OpenStreetMap's tiles (DESIGN §11.1). Images may
         * also be blob: (the heat tiles, fetched) and data: (Leaflet cancels a tile's download by pointing it
         * at a built-in data: image). */
        respond(c, 200, "OK", r.file->type,
                "Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data: blob: https://tile.openstreetmap.org; connect-src 'self'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'\r\n",
                r.file->data, r.file->size);
        return;
    case ROUTE_DATASETS: {
        struct text t = {NULL, 0, 0, 0};
        add(&t, "{\"datasets\":[");
        for (size_t i = 0; i < s->count; i++) {
            add(&t, i > 0 ? "," : "");
            add_dataset(&t, &s->datasets[i]);
        }
        add(&t, "]}\n");
        respond_json(c, &t);
        return;
    }
    case ROUTE_DATASET: {
        struct text t = {NULL, 0, 0, 0};
        add_dataset(&t, r.dataset);
        add(&t, "\n");
        respond_json(c, &t);
        return;
    }
    case ROUTE_TILE: {
        unsigned char *png;
        size_t size;
        uint64_t points;
        if (render_tile(&r.dataset->file, r.zoom, r.x, r.y, &png, &size, &points) != 0) {
            respond_error(c, 500, "out of memory");
            return;
        }
        char extra[64];
        snprintf(extra, sizeof extra, "X-Points: %" PRIu64 "\r\n", points);
        respond(c, 200, "OK", "image/png", extra, png, size);
        free(png);
        return;
    }
    case ROUTE_COUNT: {
        struct text t = {NULL, 0, 0, 0};
        add(&t, "{\"id\":\"%s\",\"count\":%" PRIu64 "}\n", r.dataset->id, area_count(&r.dataset->file, &r.box));
        respond_json(c, &t);
        return;
    }
    case ROUTE_EXPORT:
        export_csv(c, &r, s->timeout);
        return;
    case ROUTE_BAD_REQUEST:
        respond_error(c, 400, r.message);
        return;
    case ROUTE_BAD_METHOD:
        respond_error(c, 405, r.message);
        return;
    case ROUTE_NOT_FOUND:
        break;
    }
    respond_error(c, 404, r.message);
}

static void *serve_connection(void *arg)
{
    struct connection *conn = arg;
    struct client c = {.fd = conn->fd, .body = 1, .http11 = 1, .write_deadline = seconds_from_now(6 * conn->server->timeout)};
    char head[SERVER_MAX_REQUEST + 1];
    size_t used = 0;
    int complete = 0, timed_out = 0, has_nul = 0;
    /* One deadline for the whole request: a client sending a byte now and then can't hold a slot. */
    struct timespec deadline = seconds_from_now(conn->server->timeout);
    while (!complete && !has_nul && used < SERVER_MAX_REQUEST) {
        int ready = wait_for(c.fd, POLLIN, &deadline);
        timed_out = ready == 0;
        ssize_t got = ready == 1 ? read(c.fd, head + used, SERVER_MAX_REQUEST - used) : -1;
        if (got < 0 && ready == 1 && (errno == EINTR || errno == EAGAIN))
            continue;
        if (got <= 0)
            break; /* the deadline passed, the client closed, or an error */
        has_nul = memchr(head + used, '\0', (size_t)got) != NULL; /* text only: also keeps strstr below exact */
        used += (size_t)got;
        head[used] = '\0';
        complete = strstr(head, "\r\n\r\n") != NULL;
    }
    head[used] = '\0';
    if (has_nul)
        respond_error(&c, 400, "bad request");
    else if (complete)
        handle(&c, conn->server, head);
    else if (used == SERVER_MAX_REQUEST)
        respond_error(&c, strstr(head, "\r\n") == NULL ? 414 : 431,
                      strstr(head, "\r\n") == NULL ? "request line too long" : "request headers too large");
    else if (timed_out && used > 0)
        respond_error(&c, 408, "request not received in time");
    else if (used > 0)
        respond_error(&c, 400, "request cut short");
    /* Lingering close: closing with unread input makes the client's system reset the connection, which can
     * destroy our answer before the client reads it (a 414 sent while the client is still sending). So stop
     * writing, then read and drop the rest: at most 64 KB, for at most a second in all. */
    shutdown(c.fd, SHUT_WR);
    struct timespec linger = seconds_from_now(1);
    for (size_t dropped = 0; dropped < 65536 && wait_for(c.fd, POLLIN, &linger) == 1;) {
        ssize_t got = read(c.fd, head, SERVER_MAX_REQUEST);
        if (got < 0 && (errno == EINTR || errno == EAGAIN))
            continue;
        if (got <= 0)
            break;
        dropped += (size_t)got;
    }
    close(c.fd);
    free(conn);
    pthread_mutex_lock(&slots_lock);
    connections--;
    pthread_cond_signal(&slot_free);
    pthread_mutex_unlock(&slots_lock);
    return NULL;
}

int server_run(const char *host, unsigned port, unsigned timeout, const struct dataset *datasets, size_t count)
{
    struct sockaddr_in address;
    memset(&address, 0, sizeof address);
    address.sin_family = AF_INET;
    address.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &address.sin_addr) != 1) {
        fprintf(stderr, "gpstiles serve: bad --host (want an IPv4 address such as 127.0.0.1)\n");
        return 2;
    }
    signal(SIGPIPE, SIG_IGN); /* a client that hangs up mid-response must not end the server */
    int listener = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    if (listener < 0 || setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one) != 0 ||
        bind(listener, (struct sockaddr *)&address, sizeof address) != 0 || listen(listener, 128) != 0) {
        fprintf(stderr, "gpstiles serve: can't listen on %s:%u: %s\n", host, port, strerror(errno));
        if (listener >= 0)
            close(listener);
        return 1;
    }
    socklen_t length = sizeof address;
    getsockname(listener, (struct sockaddr *)&address, &length);
    printf("gpstiles serve: http://%s:%u/\n", host, (unsigned)ntohs(address.sin_port));
    fflush(stdout);

    struct server s = {datasets, count, (int)timeout};
    pthread_attr_t attributes;
    pthread_attr_init(&attributes);
    pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
    for (;;) {
        pthread_mutex_lock(&slots_lock);
        while (connections >= SERVER_MAX_CONNECTIONS)
            pthread_cond_wait(&slot_free, &slots_lock);
        connections++;
        pthread_mutex_unlock(&slots_lock);

        int fd = accept(listener, NULL, NULL);
        struct connection *c = fd >= 0 ? malloc(sizeof *c) : NULL;
        pthread_t thread;
        /* Non-blocking: every read and write waits in poll with its deadline, never inside the call. */
        if (c != NULL && fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK) == 0) {
            c->fd = fd;
            c->server = &s;
            if (pthread_create(&thread, &attributes, serve_connection, c) == 0)
                continue;
        }
        free(c);
        if (fd >= 0)
            close(fd);
        else if (errno != EINTR && errno != ECONNABORTED)
            nanosleep(&(struct timespec){0, 100000000}, NULL); /* out of file descriptors: wait, don't spin */
        pthread_mutex_lock(&slots_lock);
        connections--;
        pthread_mutex_unlock(&slots_lock);
    }
}
