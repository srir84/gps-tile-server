/* import.h: reads text rows (CSV, TSV, ...) into Z-order codes and counts what it skips (DESIGN §8).
 * A row is one line. Its longitude and latitude are two columns, found by number. */
#ifndef IMPORT_H
#define IMPORT_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define IMPORT_MAX_LINE 65536 /* longer lines are counted as malformed (bounded memory) */

struct import_options {
    unsigned lon_col, lat_col; /* 1-based column numbers */
    char delim;                /* never a character that can appear in a number */
    unsigned long skip;        /* header lines to skip at the start of each file */
};

struct import_counts {
    uint64_t rows; /* every line except blank and skipped header lines */
    uint64_t imported;
    uint64_t skipped_zero;         /* exactly (0, 0): a GPS with no fix */
    uint64_t skipped_out_of_range; /* outside geo_valid_lon / geo_valid_lat */
    uint64_t skipped_malformed;    /* missing column, not a plain decimal, or too long */
};

enum import_result { IMPORT_BLANK, IMPORT_POINT, IMPORT_ZERO, IMPORT_OUT_OF_RANGE, IMPORT_MALFORMED };

/* Parses a plain decimal (sign, digits, point, exponent) of exactly `length` bytes. Anything
 * else fails, including "nan", "inf", hex and spaces. text[length] must be '\0'.
 * Returns 0 if ok; *out may be ±infinity. */
int import_parse_number(const char *text, size_t length, double *out);

/* 1 if c can separate columns: not part of a number, not a line ending, not '\0'. */
int import_delim_ok(char c);

/* Classifies one line (without its '\n'; a trailing '\r' is ignored) and, for IMPORT_POINT,
 * sets *code. line[length] must be '\0'. The line may be changed. */
enum import_result import_row(char *line, size_t length, const struct import_options *options, uint64_t *code);

/* Reads every line of `in`, adds to *counts, and appends each point's code to `out` as
 * 8 little-endian bytes. Returns 0, or -1 on a read or write error (check ferror on each). */
int import_stream(FILE *in, FILE *out, const struct import_options *options, struct import_counts *counts);

#endif
