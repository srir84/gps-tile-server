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

struct route server_route(const char *method, const char *target, const struct dataset *datasets, size_t count)
{
    if (strcmp(method, "GET") != 0 && strcmp(method, "HEAD") != 0)
        return error_route(ROUTE_BAD_METHOD, "only GET and HEAD are supported");
    size_t length = strcspn(target, "?"); /* the path; no route uses the query yet */
    const char *end = target + length;
    static const char api[] = "/api/datasets", tiles[] = "/tiles/";
    if (length == sizeof api - 1 && memcmp(target, api, length) == 0)
        return (struct route){.kind = ROUTE_DATASETS};
    if (length > sizeof api && memcmp(target, api, sizeof api - 1) == 0 && target[sizeof api - 1] == '/') {
        const char *id = target + sizeof api;
        const struct dataset *d = memchr(id, '/', (size_t)(end - id)) == NULL
                                      ? find_dataset(id, (size_t)(end - id), datasets, count)
                                      : NULL;
        if (d == NULL)
            return error_route(ROUTE_NOT_FOUND, memchr(id, '/', (size_t)(end - id)) == NULL ? "unknown dataset" : "not found");
        return (struct route){.kind = ROUTE_DATASET, .dataset = d};
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

/* One connection: its (non-blocking) socket, whether the answer has a body (not for HEAD), and the time its
 * whole answer must be sent by (a client that stops reading can't hold a connection slot for long). */
struct client {
    int fd;
    int body;
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
    }
    return 0;
}

static void respond(struct client *c, int status, const char *reason, const char *type, const char *extra,
                    const void *body, size_t size)
{
    char head[1024]; /* status line and headers: a few hundred bytes */
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
 * header lines "Name: value", no space before the colon, exactly one Host for HTTP/1.1. */
struct request {
    char *method, *target;
    const char *host; /* NULL if none (HTTP/1.0) */
    size_t host_length;
};

/* Parses the head in place (it ends with an empty line). Returns NULL, or why it is a bad request. */
static const char *parse_head(char *head, struct request *r)
{
    char *line_end = strstr(head, "\r\n");
    char *space = strchr(head, ' ');
    char *space2 = space != NULL && space < line_end ? strchr(space + 1, ' ') : NULL;
    if (space == NULL || space2 == NULL || space2 > line_end || space == head || space[1] != '/' ||
        line_end - (space2 + 1) != 8 || (strncmp(space2 + 1, "HTTP/1.0", 8) != 0 && strncmp(space2 + 1, "HTTP/1.1", 8) != 0))
        return "bad request line";
    int http11 = space2[8] == '1';
    *space = '\0';
    *space2 = '\0';
    r->method = head;
    r->target = space + 1;
    r->host = NULL;
    int hosts = 0;
    for (char *line = line_end + 2; strncmp(line, "\r\n", 2) != 0; line = strstr(line, "\r\n") + 2) {
        size_t length = strcspn(line, "\r\n"), name = strcspn(line, ":\r\n");
        if (name == 0 || name >= length || strcspn(line, " \t") < name)
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
    if (req.host != NULL && !safe_host(req.host, req.host_length)) {
        respond_error(c, 403, "this server only answers requests for localhost or an IP address");
        return;
    }
    struct route r = server_route(req.method, req.target, s->datasets, s->count);
    switch (r.kind) {
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
    struct client c = {conn->fd, 1, seconds_from_now(6 * conn->server->timeout)};
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
