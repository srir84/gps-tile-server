/* import.c: text rows → Z-order codes, declared in import.h (DESIGN §8). */
#include "import.h"

#include <stdlib.h>
#include <string.h>

#include "geo.h"

#define NUMBER_CHARS "0123456789+-.eE"
#define READ_SIZE (1u << 20) /* must be larger than IMPORT_MAX_LINE */

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
    if (lon == 0.0 && lat == 0.0)
        return IMPORT_ZERO;
    if (!geo_valid_lon(lon) || !geo_valid_lat(lat))
        return IMPORT_OUT_OF_RANGE;
    *code = geo_code(geo_world_x(lon), geo_world_y(lat));
    return IMPORT_POINT;
}

struct line_reader {
    FILE *in;
    char *buf; /* READ_SIZE + 1 bytes: room for a '\0' after the last line */
    size_t start, end;
    int eof;
};

enum { LINE_OK, LINE_TOO_LONG, LINE_END, LINE_ERROR };

/* Next line, '\0'-terminated in place of its '\n'. A last line without '\n' still counts.
 * A line longer than IMPORT_MAX_LINE is read to its end and reported as LINE_TOO_LONG. */
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
            if (too_long || n > IMPORT_MAX_LINE)
                return LINE_TOO_LONG;
            *line = data;
            *length = n;
            return LINE_OK;
        }
        if (r->eof)
            return too_long ? LINE_TOO_LONG : LINE_END;
        if (available > IMPORT_MAX_LINE) {
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

int import_stream(FILE *in, FILE *out, const struct import_options *options, struct import_counts *counts)
{
    struct line_reader reader = {in, malloc(READ_SIZE + 1), 0, 0, 0};
    if (reader.buf == NULL)
        return -1;

    int status = 0;
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

        uint64_t code = 0;
        enum import_result result = got == LINE_TOO_LONG ? IMPORT_MALFORMED : import_row(line, length, options, &code);
        if (result == IMPORT_BLANK)
            continue;
        counts->rows++;
        switch (result) {
        case IMPORT_POINT:
            if (write_code(out, code) != 0) {
                status = -1;
                goto done;
            }
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
        case IMPORT_BLANK: /* skipped above */
            break;
        }
    }
done:
    free(reader.buf);
    return status;
}
