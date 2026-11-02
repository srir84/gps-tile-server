/* import.h: reads text rows (CSV, TSV, ...) into Z-order codes and counts what it skips (DESIGN §8).
 * A row is one line. Its longitude and latitude are two columns, found by number; or (--polyline) one column holds a
 * list of [lon,lat] pairs, each one a point; or (--gpx) a row is a GPX <trkpt> start tag, its lat and lon attributes. */
#ifndef IMPORT_H
#define IMPORT_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define IMPORT_MAX_LINE 65536             /* longer lines are counted as malformed (bounded memory) */
#define IMPORT_MAX_POLYLINE_LINE 1000000   /* the same for a polyline row (one trip): Porto's longest is 84,640 */
#define IMPORT_MAX_PAIRS (IMPORT_MAX_POLYLINE_LINE / 5 + 1) /* "[0,0]" is the shortest pair */
#define IMPORT_MAX_GPX_TAG 4096 /* a <trkpt ...> start tag longer than this is malformed (bounded memory) */

struct import_options {
    unsigned lon_col, lat_col; /* 1-based column numbers (0 with polyline_col) */
    char delim;                /* never a character that can appear in a number, nor '"', '[' or ']' with polyline_col */
    unsigned long skip;        /* header lines to skip at the start of each file */
    unsigned polyline_col;     /* 0, or the 1-based column (CSV, maybe quoted) holding [[lon,lat],...] */
    int gpx;                   /* 1: the input is GPX (XML), not rows of columns */
};

struct import_counts {
    uint64_t rows; /* every line except blank and skipped header lines */
    uint64_t imported;
    uint64_t skipped_zero;         /* exactly (0, 0): a GPS with no fix */
    uint64_t skipped_out_of_range; /* outside geo_valid_lon / geo_valid_lat */
    uint64_t skipped_malformed;    /* rows: missing column, not a plain decimal (or not a pair list), or too long */
    uint64_t points;               /* polyline rows only: the pairs of the well-formed rows (imported + zero + out of range) */
};

enum import_result { IMPORT_BLANK, IMPORT_POINT, IMPORT_ZERO, IMPORT_OUT_OF_RANGE, IMPORT_MALFORMED };

/* Parses a plain decimal (sign, digits, point, exponent) of exactly `length` bytes. Anything
 * else fails, including "nan", "inf", hex and spaces. text[length] must be '\0'.
 * Returns 0 if ok; *out may be ±infinity. */
int import_parse_number(const char *text, size_t length, double *out);

/* 1 if c can separate columns: not part of a number, not a line ending, not '\0'. */
int import_delim_ok(char c);

/* Classifies a place: IMPORT_ZERO, IMPORT_OUT_OF_RANGE, or IMPORT_POINT with *code set. */
enum import_result import_point(double lon, double lat, uint64_t *code);

/* Finds column `col` (1-based) of a CSV line where a field may be quoted ("...", with "" for a quote inside): sets
 * *start and *field_length to the field without its quotes. Returns 0, or -1 if the line has fewer columns, or a
 * quote anywhere in it isn't closed or is followed by anything but the delimiter. */
int import_csv_column(const char *line, size_t length, char delim, unsigned col, const char **start,
                      size_t *field_length);

/* Reads a whole list "[[lon,lat],[lon,lat],...]" (spaces and tabs allowed between its parts; numbers as
 * import_parse_number, at most 63 characters) into lonlat, 2 values a pair, room for max_pairs pairs. Returns the
 * number of pairs (0 for "[]"), or -1 if the text isn't exactly such a list or has more pairs. */
long import_parse_polyline(const char *text, size_t length, double *lonlat, size_t max_pairs);

/* One GPX <trkpt> start tag's attributes, text[0..n) (what follows "<trkpt" up to its '>'; a trailing '/' is
 * allowed): IMPORT_MALFORMED unless lat and lon are each name="number" or name='number' (spaces around '=' allowed,
 * numbers as import_parse_number, at most 63 characters, each name once); else its place's class and *code. */
enum import_result import_gpx_point(const char *text, size_t n, uint64_t *code);

/* Classifies one line (without its '\n'; a trailing '\r' is ignored) and, for IMPORT_POINT,
 * sets *code. line[length] must be '\0'. The line may be changed. */
enum import_result import_row(char *line, size_t length, const struct import_options *options, uint64_t *code);

/* Reads every line of `in`, adds to *counts, and appends each point's code to `out` as
 * 8 little-endian bytes. Returns 0, or -1 on a read or write error (check ferror on each). */
int import_stream(FILE *in, FILE *out, const struct import_options *options, struct import_counts *counts);

#endif
