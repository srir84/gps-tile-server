/* import.c: text rows → Z-order codes, declared in import.h (DESIGN §8). */
#include "import.h"

#include <stdlib.h>
#include <string.h>

#include "geo.h"

#define NUMBER_CHARS "0123456789+-.eE"
#define READ_SIZE (1u << 20) /* must be larger than IMPORT_MAX_LINE and IMPORT_MAX_POLYLINE_LINE */
_Static_assert(IMPORT_MAX_LINE < READ_SIZE && IMPORT_MAX_POLYLINE_LINE < READ_SIZE, "a row must fit the read buffer");

int import_parse_number(const char *text, size_t length, double *out)
{
    if (length == 0)
        return -1;
    for (size_t i = 0; i < length; i++) {
        if (text[i] == '\0' || strchr(NUMBER_CHARS, text[i]) == NULL)
            return -1;
    }
    char *end; /* strtod stops at text[length], which is '\0' */
    double value = strtod(text, &end);
    if (end != text + length)
        return -1;
    *out = value;
    return 0;
}

int import_delim_ok(char c)
{
    return c != '\0' && c != '\n' && c != '\r' && strchr(NUMBER_CHARS, c) == NULL;
}

/* Finds column `col` (1-based). Returns 0 and sets *start and *length, or -1 if the line is too short. */
static int find_column(char *line, size_t length, char delim, unsigned col, char **start, size_t *field_length)
{
    char *p = line, *end = line + length;
    for (unsigned i = 1; i < col; i++) {
        p = memchr(p, delim, (size_t)(end - p));
        if (p == NULL)
            return -1;
        p++;
    }
    char *next = memchr(p, delim, (size_t)(end - p));
    *start = p;
    *field_length = (size_t)((next != NULL ? next : end) - p);
    return 0;
}

enum import_result import_point(double lon, double lat, uint64_t *code)
{
    if (lon == 0.0 && lat == 0.0)
        return IMPORT_ZERO;
    if (!geo_valid_lon(lon) || !geo_valid_lat(lat))
        return IMPORT_OUT_OF_RANGE;
    *code = geo_code(geo_world_x(lon), geo_world_y(lat));
    return IMPORT_POINT;
}

int import_csv_column(const char *line, size_t length, char delim, unsigned col, const char **start,
                      size_t *field_length)
{
    size_t i = 0;
    int found = 0;
    for (unsigned k = 1;; k++) { /* every field, so a broken quote anywhere in the row refuses it */
        size_t begin, end;
        if (i < length && line[i] == '"') {
            begin = ++i;
            for (;;) {
                const char *quote = memchr(line + i, '"', length - i);
                if (quote == NULL)
                    return -1; /* not closed */
                i = (size_t)(quote - line);
                if (i + 1 < length && line[i + 1] == '"') {
                    i += 2; /* "" is a quote inside the field */
                    continue;
                }
                break;
            }
            end = i++;
            if (i < length && line[i] != delim)
                return -1;
        } else {
            begin = i;
            const char *next = memchr(line + i, delim, length - i);
            i = next != NULL ? (size_t)(next - line) : length;
            end = i;
        }
        if (k == col) {
            *start = line + begin;
            *field_length = end - begin;
            found = 1;
        }
        if (i >= length)
            return found ? 0 : -1; /* the row's end: too few columns unless col was among them */
        i++;                       /* past the delimiter */
    }
}

static size_t skip_blanks(const char *s, size_t i, size_t n)
{
    while (i < n && (s[i] == ' ' || s[i] == '\t'))
        i++;
    return i;
}

/* One number of a pair list: up to the next ',', ']', space or tab. */
static int list_number(const char *s, size_t *i, size_t n, double *out)
{
    char text[64];
    size_t start = *i;
    while (*i < n && s[*i] != ',' && s[*i] != ']' && s[*i] != ' ' && s[*i] != '\t')
        (*i)++;
    size_t length = *i - start;
    if (length == 0 || length >= sizeof text)
        return -1;
    memcpy(text, s + start, length);
    text[length] = '\0';
    return import_parse_number(text, length, out);
}

long import_parse_polyline(const char *s, size_t n, double *lonlat, size_t max_pairs)
{
    size_t i = skip_blanks(s, 0, n), pairs = 0;
    if (i >= n || s[i++] != '[')
        return -1;
    i = skip_blanks(s, i, n);
    if (i < n && s[i] == ']')
        return skip_blanks(s, i + 1, n) == n ? 0 : -1;
    for (;;) {
        if (pairs == max_pairs || i >= n || s[i++] != '[')
            return -1;
        double *pair = lonlat + 2 * pairs;
        i = skip_blanks(s, i, n);
        if (list_number(s, &i, n, &pair[0]) != 0)
            return -1;
        i = skip_blanks(s, i, n);
        if (i >= n || s[i++] != ',')
            return -1;
        i = skip_blanks(s, i, n);
        if (list_number(s, &i, n, &pair[1]) != 0)
            return -1;
        i = skip_blanks(s, i, n);
        if (i >= n || s[i++] != ']')
            return -1;
        pairs++;
        i = skip_blanks(s, i, n);
        if (i >= n)
            return -1; /* the list isn't closed */
        if (s[i] == ',') {
            i = skip_blanks(s, i + 1, n);
            continue;
        }
        if (s[i] != ']')
            return -1;
        return skip_blanks(s, i + 1, n) == n ? (long)pairs : -1;
    }
}

#define GPX_TAG "<trkpt"
#define GPX_TAG_LENGTH 6
/* XML's 4 space characters: a test, not strchr (which also matches a string's ending '\0', so a NUL byte would pass). */
static int xml_space(char c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

/* The value of attribute `name` among a start tag's attributes text[0..n): name="v" or name='v', spaces allowed
 * around '='. Returns 1 found (*value, *length set), 0 not there, -1 the attributes are broken or name comes twice. */
static int tag_attribute(const char *text, size_t n, const char *name, const char **value, size_t *length)
{
    size_t name_length = strlen(name), i = 0;
    int found = 0;
    for (;;) {
        while (i < n && xml_space(text[i]))
            i++;
        if (i >= n)
            return found;
        size_t start = i;
        while (i < n && text[i] != '=' && !xml_space(text[i]))
            i++;
        size_t end = i;
        while (i < n && xml_space(text[i]))
            i++;
        if (end == start || i >= n || text[i] != '=')
            return -1; /* not name=value */
        i++;
        while (i < n && xml_space(text[i]))
            i++;
        if (i >= n || (text[i] != '"' && text[i] != '\''))
            return -1;
        char quote = text[i++];
        const char *close = memchr(text + i, quote, n - i);
        if (close == NULL)
            return -1;
        if (end - start == name_length && memcmp(text + start, name, name_length) == 0) {
            if (found)
                return -1; /* twice: which one? */
            found = 1;
            *value = text + i;
            *length = (size_t)(close - (text + i));
        }
        i = (size_t)(close - text) + 1;
    }
}

/* An attribute's number: at most 63 characters, then import_parse_number. Returns 0 if ok. */
static int attribute_number(const char *text, size_t length, double *out)
{
    char copy[64];
    if (length == 0 || length >= sizeof copy)
        return -1;
    memcpy(copy, text, length);
    copy[length] = '\0';
    return import_parse_number(copy, length, out);
}

enum import_result import_gpx_point(const char *text, size_t n, uint64_t *code)
{
    const char *lat_text, *lon_text;
    size_t lat_length, lon_length;
    double lat, lon;
    if (n > 0 && text[n - 1] == '/')
        n--; /* <trkpt lat="1" lon="2"/> */
    if (tag_attribute(text, n, "lat", &lat_text, &lat_length) != 1 ||
        tag_attribute(text, n, "lon", &lon_text, &lon_length) != 1 ||
        attribute_number(lat_text, lat_length, &lat) != 0 || attribute_number(lon_text, lon_length, &lon) != 0)
        return IMPORT_MALFORMED;
    return import_point(lon, lat, code);
}

enum import_result import_row(char *line, size_t length, const struct import_options *options, uint64_t *code)
{
    if (length > 0 && line[length - 1] == '\r')
        line[--length] = '\0';
    if (length == 0)
        return IMPORT_BLANK;

    char *lon_text, *lat_text;
    size_t lon_length, lat_length;
    double lon, lat;
    if (find_column(line, length, options->delim, options->lon_col, &lon_text, &lon_length) != 0 ||
        find_column(line, length, options->delim, options->lat_col, &lat_text, &lat_length) != 0)
        return IMPORT_MALFORMED;
    /* End each field so strtod can't read on into the delimiter (with --delim x, "0x10" is hex). */
    lon_text[lon_length] = '\0';
    lat_text[lat_length] = '\0';
    if (import_parse_number(lon_text, lon_length, &lon) != 0 || import_parse_number(lat_text, lat_length, &lat) != 0)
        return IMPORT_MALFORMED;
    return import_point(lon, lat, code);
}

struct line_reader {
    FILE *in;
    char *buf; /* READ_SIZE + 1 bytes: room for a '\0' after the last line */
    size_t start, end;
    int eof;
    size_t max_line; /* IMPORT_MAX_LINE, or IMPORT_MAX_POLYLINE_LINE: less than READ_SIZE */
};

enum { LINE_OK, LINE_TOO_LONG, LINE_END, LINE_ERROR };

/* Next line, '\0'-terminated in place of its '\n'. A last line without '\n' still counts.
 * A line longer than r->max_line is read to its end and reported as LINE_TOO_LONG. */
static int next_line(struct line_reader *r, char **line, size_t *length)
{
    int too_long = 0;
    for (;;) {
        char *data = r->buf + r->start;
        size_t available = r->end - r->start;
        char *newline = memchr(data, '\n', available);
        if (newline != NULL || (r->eof && available > 0)) {
            size_t n = newline != NULL ? (size_t)(newline - data) : available;
            data[n] = '\0';
            r->start += n + (newline != NULL);
            if (too_long || n > r->max_line)
                return LINE_TOO_LONG;
            *line = data;
            *length = n;
            return LINE_OK;
        }
        if (r->eof)
            return too_long ? LINE_TOO_LONG : LINE_END;
        if (available > r->max_line) {
            too_long = 1; /* drop what we have, keep looking for the end of this line */
            r->end = 0;
        } else {
            memmove(r->buf, data, available);
            r->end = available;
        }
        r->start = 0;
        size_t got = fread(r->buf + r->end, 1, READ_SIZE - r->end, r->in);
        if (got == 0) {
            if (ferror(r->in))
                return LINE_ERROR;
            r->eof = 1;
        }
        r->end += got;
    }
}

static int write_code(FILE *out, uint64_t code)
{
    unsigned char bytes[8];
    for (int i = 0; i < 8; i++)
        bytes[i] = (unsigned char)(code >> (8 * i));
    return fwrite(bytes, 1, sizeof bytes, out) == sizeof bytes ? 0 : -1;
}

/* Counts one classified row or point, and writes a kept point. Returns 0, or -1 on a write error. */
static int take(enum import_result result, uint64_t code, FILE *out, struct import_counts *counts)
{
    switch (result) {
    case IMPORT_POINT:
        if (write_code(out, code) != 0)
            return -1;
        counts->imported++;
        break;
    case IMPORT_ZERO:
        counts->skipped_zero++;
        break;
    case IMPORT_OUT_OF_RANGE:
        counts->skipped_out_of_range++;
        break;
    case IMPORT_MALFORMED:
        counts->skipped_malformed++;
        break;
    case IMPORT_BLANK:
        break;
    }
    return 0;
}

/* A polyline row (not blank): malformed unless its column is a whole pair list; then every pair is a point.
 * lonlat has room for IMPORT_MAX_PAIRS pairs. Returns 0, or -1 on a write error. */
static int polyline_row(const char *line, size_t length, const struct import_options *options, double *lonlat,
                        FILE *out, struct import_counts *counts)
{
    const char *field;
    size_t field_length;
    long pairs = -1;
    if (import_csv_column(line, length, options->delim, options->polyline_col, &field, &field_length) == 0)
        pairs = import_parse_polyline(field, field_length, lonlat, IMPORT_MAX_PAIRS);
    if (pairs < 0)
        return take(IMPORT_MALFORMED, 0, out, counts);
    for (long k = 0; k < pairs; k++) {
        uint64_t code = 0;
        counts->points++;
        enum import_result result = import_point(lonlat[2 * k], lonlat[2 * k + 1], &code); /* sets code first */
        if (take(result, code, out, counts) != 0)
            return -1;
    }
    return 0;
}

/* The next "<trkpt" followed by a space, '/' or '>' in s[i..n), or n (a "<trkpt" in the last 6 bytes isn't known yet). */
static size_t next_trkpt(const char *s, size_t i, size_t n)
{
    while (i + GPX_TAG_LENGTH < n) {
        const char *lt = memchr(s + i, '<', n - i - GPX_TAG_LENGTH);
        if (lt == NULL)
            return n;
        i = (size_t)(lt - s);
        char after = s[i + GPX_TAG_LENGTH];
        if (memcmp(s + i, GPX_TAG, GPX_TAG_LENGTH) == 0 && (xml_space(after) || after == '/' || after == '>'))
            return i;
        i++;
    }
    return n;
}

/* Where the tag ends in s[i..n): its closing '>' (the first outside a quoted value: '>' is allowed inside one), a '<'
 * or a NUL (never in a tag, even quoted: the tag is broken, and a stray quote can't hide the tags after it), or NULL. */
static const char *tag_end(const char *s, size_t i, size_t n)
{
    char quote = 0;
    for (; i < n; i++) {
        if (s[i] == '<' || s[i] == '\0') {
            return s + i;
        } else if (quote != 0) {
            if (s[i] == quote)
                quote = 0;
        } else if (s[i] == '"' || s[i] == '\'') {
            quote = s[i];
        } else if (s[i] == '>') {
            return s + i;
        }
    }
    return NULL;
}

/* GPX: the stream is read in chunks, not lines (a tag may span lines, and a line hold many tags). Every <trkpt start
 * tag is a row; one with no '>' within IMPORT_MAX_GPX_TAG bytes (or before the end) is malformed. */
static int gpx_stream(FILE *in, FILE *out, struct import_counts *counts)
{
    char *buf = malloc(READ_SIZE);
    if (buf == NULL)
        return -1;
    size_t start = 0, end = 0;
    int eof = 0, status = 0;
    for (;;) {
        size_t at = next_trkpt(buf, start, end);
        if (at < end) {
            size_t room = end - at < IMPORT_MAX_GPX_TAG ? end - at : IMPORT_MAX_GPX_TAG;
            const char *gt = tag_end(buf, at + GPX_TAG_LENGTH, at + room);
            if (gt != NULL || end - at >= IMPORT_MAX_GPX_TAG || eof) {
                uint64_t code = 0;
                enum import_result result = IMPORT_MALFORMED; /* too long, broken by a '<', or cut off by the end */
                if (gt != NULL && *gt == '>')
                    result = import_gpx_point(buf + at + GPX_TAG_LENGTH, (size_t)(gt - buf) - at - GPX_TAG_LENGTH, &code);
                counts->rows++;
                if (take(result, code, out, counts) != 0) {
                    status = -1;
                    break;
                }
                start = gt != NULL && *gt == '>' ? (size_t)(gt - buf) + 1 : at + GPX_TAG_LENGTH;
                continue;
            }
        }
        if (eof)
            break;
        /* Keep what may still be a tag: from a "<trkpt" waiting for its '>', else the last 6 bytes. */
        size_t keep = at < end ? at : (end - start > GPX_TAG_LENGTH ? end - GPX_TAG_LENGTH : start);
        memmove(buf, buf + keep, end - keep);
        end -= keep;
        start = 0;
        size_t got = fread(buf + end, 1, READ_SIZE - end, in);
        if (got == 0) {
            if (ferror(in)) {
                status = -1;
                break;
            }
            eof = 1;
        }
        end += got;
    }
    free(buf);
    return status;
}

int import_stream(FILE *in, FILE *out, const struct import_options *options, struct import_counts *counts)
{
    if (options->gpx)
        return gpx_stream(in, out, counts);
    int polyline = options->polyline_col != 0;
    struct line_reader reader = {in, malloc(READ_SIZE + 1), 0, 0, 0,
                                 polyline ? IMPORT_MAX_POLYLINE_LINE : IMPORT_MAX_LINE};
    double *lonlat = polyline ? malloc(2 * IMPORT_MAX_PAIRS * sizeof *lonlat) : NULL;
    int status = 0;
    if (reader.buf == NULL || (polyline && lonlat == NULL)) {
        status = -1;
        goto done;
    }

    unsigned long line_number = 0;
    char *line;
    size_t length;
    for (;;) {
        int got = next_line(&reader, &line, &length);
        if (got == LINE_END)
            break;
        if (got == LINE_ERROR) {
            status = -1;
            break;
        }
        if (++line_number <= options->skip)
            continue;

        if (got == LINE_TOO_LONG) {
            counts->rows++;
            status = take(IMPORT_MALFORMED, 0, out, counts);
        } else if (polyline) {
            if (length > 0 && line[length - 1] == '\r') /* one '\r', as import_row */
                line[--length] = '\0';
            if (length == 0)
                continue; /* blank: not a row */
            counts->rows++;
            status = polyline_row(line, length, options, lonlat, out, counts);
        } else {
            uint64_t code = 0;
            enum import_result result = import_row(line, length, options, &code);
            if (result == IMPORT_BLANK)
                continue;
            counts->rows++;
            status = take(result, code, out, counts);
        }
        if (status != 0)
            break;
    }
done:
    free(lonlat);
    free(reader.buf);
    return status;
}
