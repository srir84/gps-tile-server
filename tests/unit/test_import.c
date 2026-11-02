/* Unit and random tests for src/import.c (TESTING.md §9, step 2): the number parser, one row,
 * and the line reader. Rows against known tiles; the reader against splitting lines by hand. */
#include "suites.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "geo.h"
#include "import.h"

static const struct import_options TDRIVE = {3, 4, ',', 0, 0, 0};
static const struct import_options PORTO = {0, 0, ',', 1, 9, 0};

static int parses(const char *text, double expected)
{
    double value;
    return import_parse_number(text, strlen(text), &value) == 0 && value == expected;
}

static int refused(const char *text)
{
    double value;
    return import_parse_number(text, strlen(text), &value) != 0;
}

static enum import_result row(const char *text, uint64_t *code)
{
    static char line[256];
    snprintf(line, sizeof line, "%s", text);
    return import_row(line, strlen(line), &TDRIVE, code);
}

static void plain_decimals_parse_and_nothing_else_does(void)
{
    CHECK(parses("116.51172", 116.51172) && parses("-74.006", -74.006) && parses("+3", 3.0));
    CHECK(parses(".5", 0.5) && parses("5.", 5.0) && parses("1e3", 1000.0) && parses("-1E-1", -0.1));
    CHECK(parses("1e999", INFINITY)); /* a number, just out of range: the caller decides */
    const char *bad[] = {"", "nan", "inf", "infinity", "0x10", " 1", "1 ", "1,5", "1.2.3", "1e", "e5", ".", "-",
                         "+-1", "--1", "abc", "116.5x"};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++)
        CHECK(refused(bad[i]));
    double value;
    CHECK(import_parse_number("116\0junk", 8, &value) != 0); /* a NUL can't hide the rest of the field */
}

static void delimiters_cannot_be_part_of_a_number(void)
{
    CHECK(import_delim_ok(',') && import_delim_ok('\t') && import_delim_ok(';') && import_delim_ok(' '));
    const char *bad = "0123456789+-.eE\n\r";
    for (const char *c = bad; *c != '\0'; c++)
        CHECK(!import_delim_ok(*c));
    CHECK(!import_delim_ok('\0'));
}

static void a_row_becomes_its_known_tile(void)
{
    uint64_t code = 0;
    CHECK(row("1,2008-02-02 15:36:08,116.391,39.907\r", &code) == IMPORT_POINT);
    struct geo_tile tile = geo_tile_of(code, 10);
    CHECK_EQ_U64(843, tile.x); /* DESIGN §13 */
    CHECK_EQ_U64(388, tile.y);
}

static void rows_are_sorted_into_the_right_bucket(void)
{
    uint64_t code;
    CHECK(row("", &code) == IMPORT_BLANK && row("\r", &code) == IMPORT_BLANK);
    CHECK(row("1,t,0,0", &code) == IMPORT_ZERO && row("1,t,-0.0,0.0\r", &code) == IMPORT_ZERO);
    CHECK(row("1,t,193.6,39.9", &code) == IMPORT_OUT_OF_RANGE && row("1,t,116.4,95.2", &code) == IMPORT_OUT_OF_RANGE);
    CHECK(row("1,t,1e999,0", &code) == IMPORT_OUT_OF_RANGE);
    CHECK(row("1,t,116.5", &code) == IMPORT_MALFORMED && row("1,t,116.5,", &code) == IMPORT_MALFORMED);
    CHECK(row("1,t,abc,39.9", &code) == IMPORT_MALFORMED && row(" ", &code) == IMPORT_MALFORMED);
    CHECK(row("1,t,116.5,39.9,extra,columns", &code) == IMPORT_POINT);

    struct import_options x_delim = {1, 2, 'x', 0, 0, 0};
    char hex_looking[] = "0x10"; /* lon 0, lat 10: strtod must not read "0x10" as one hex number */
    CHECK(import_row(hex_looking, strlen(hex_looking), &x_delim, &code) == IMPORT_POINT);
    CHECK_EQ_U64(geo_code(geo_world_x(0.0), geo_world_y(10.0)), code);

    struct import_options lat_first = {2, 1, '\t', 0, 0, 0};
    char line[] = "39.907\t116.391";
    CHECK(import_row(line, strlen(line), &lat_first, &code) == IMPORT_POINT);
    CHECK_EQ_U64(843, geo_tile_of(code, 10).x);
}

/* Writes `data` to a temp file and imports it with TDRIVE options; codes go to *out (rewound). */
static int import_with(const struct import_options *given, const char *data, size_t length, unsigned long skip,
                       struct import_counts *counts, FILE **out)
{
    struct import_options options = *given;
    options.skip = skip;
    FILE *in = tmpfile();
    *out = tmpfile();
    if (in == NULL || *out == NULL || fwrite(data, 1, length, in) != length)
        return -1;
    rewind(in);
    memset(counts, 0, sizeof *counts);
    int status = import_stream(in, *out, &options, counts);
    fclose(in);
    rewind(*out);
    return status;
}

static int import_bytes(const char *data, size_t length, unsigned long skip, struct import_counts *counts, FILE **out)
{
    return import_with(&TDRIVE, data, length, skip, counts, out);
}

static uint64_t read_code(FILE *f)
{
    unsigned char b[8] = {0};
    if (fread(b, 1, 8, f) != 8)
        return UINT64_MAX;
    uint64_t code = 0;
    for (int i = 7; i >= 0; i--)
        code = (code << 8) | b[i];
    return code;
}

static void codes_are_written_as_8_little_endian_bytes(void)
{
    const char data[] = "1,t,116.391,39.907\n1,t,0,0\n1,t,-74.006,40.7128";
    struct import_counts counts;
    FILE *out;
    CHECK(import_bytes(data, sizeof data - 1, 0, &counts, &out) == 0);
    unsigned char first[8];
    CHECK(fread(first, 1, 8, out) == 8);
    uint64_t expected = geo_code(geo_world_x(116.391), geo_world_y(39.907));
    for (int i = 0; i < 8; i++)
        CHECK_EQ_U64((expected >> (8 * i)) & 0xFF, first[i]);
    CHECK_EQ_U64(geo_code(geo_world_x(-74.006), geo_world_y(40.7128)), read_code(out));
    CHECK(fgetc(out) == EOF);
    fclose(out);
    CHECK_EQ_U64(3, counts.rows);
    CHECK_EQ_U64(2, counts.imported);
}

static void header_lines_are_skipped_before_counting(void)
{
    const char data[] = "id,time,lon,lat\n\n1,t,116.5,39.9\n";
    struct import_counts counts;
    FILE *out;
    CHECK(import_bytes(data, sizeof data - 1, 2, &counts, &out) == 0);
    fclose(out);
    CHECK_EQ_U64(1, counts.rows);
    CHECK_EQ_U64(1, counts.imported);
}

#define BIG (3u << 20) /* 3 MiB: three times the reader's buffer */
static char big[BIG];

static void random_files_split_into_the_same_lines_as_by_hand(void)
{
    /* Random lines (some longer than IMPORT_MAX_LINE, some ending in "\r", maybe no final newline),
     * imported in one go, must give the same counts and codes as import_row on each line. */
    for (int run = 0; run < 4; run++) {
        size_t length = 0;
        while (length < BIG - 200000) {
            uint64_t r = check_rand();
            size_t line_length = (r % 64 == 0) ? (size_t)(r >> 8) % 140000 : (size_t)(r >> 8) % 60;
            if (r % 5 == 0) {
                length += (size_t)snprintf(big + length, 64, "1,t,%.5f,%.5f", (double)(r % 360000) / 1000 - 180,
                                           (double)((r >> 20) % 170000) / 1000 - 85);
            } else {
                for (size_t i = 0; i < line_length; i++)
                    big[length++] = "0123456789.,-e\r ab"[check_rand() % 18];
            }
            big[length++] = '\n';
        }
        if (run % 2 == 1)
            length--; /* no final newline */

        struct import_counts counts, expected = {0, 0, 0, 0, 0, 0};
        FILE *out;
        CHECK(import_bytes(big, length, 0, &counts, &out) == 0);
        size_t start = 0;
        while (start < length) {
            char *newline = memchr(big + start, '\n', length - start);
            size_t end = newline != NULL ? (size_t)(newline - big) : length;
            static char line[IMPORT_MAX_LINE + 1];
            size_t n = end - start;
            if (n > IMPORT_MAX_LINE) {
                expected.rows++;
                expected.skipped_malformed++;
            } else {
                memcpy(line, big + start, n);
                line[n] = '\0';
                uint64_t code = 0;
                enum import_result result = import_row(line, n, &TDRIVE, &code);
                if (result != IMPORT_BLANK)
                    expected.rows++;
                if (result == IMPORT_POINT) {
                    expected.imported++;
                    CHECK_EQ_U64(code, read_code(out));
                }
                expected.skipped_zero += result == IMPORT_ZERO;
                expected.skipped_out_of_range += result == IMPORT_OUT_OF_RANGE;
                expected.skipped_malformed += result == IMPORT_MALFORMED;
            }
            start = end + 1;
        }
        int extra = fgetc(out);
        fclose(out);
        CHECK(extra == EOF);
        CHECK_EQ_U64(expected.rows, counts.rows);
        CHECK_EQ_U64(expected.imported, counts.imported);
        CHECK_EQ_U64(expected.skipped_zero, counts.skipped_zero);
        CHECK_EQ_U64(expected.skipped_out_of_range, counts.skipped_out_of_range);
        CHECK_EQ_U64(expected.skipped_malformed, counts.skipped_malformed);
        CHECK(counts.imported > 100 && counts.skipped_malformed > 100);
    }
}

/* Column `col` of a CSV line as text ("" when import_csv_column refuses the line). */
static const char *column(const char *line, unsigned col)
{
    static char text[256];
    const char *start;
    size_t length;
    if (import_csv_column(line, strlen(line), ',', col, &start, &length) != 0)
        return "";
    snprintf(text, sizeof text, "[%.*s]", (int)length, start);
    return text;
}

static void quoted_csv_columns_keep_their_commas(void)
{
    CHECK(strcmp(column("a,\"[[1,2],[3,4]]\",c", 2), "[[[1,2],[3,4]]]") == 0);
    CHECK(strcmp(column("a,\"[[1,2],[3,4]]\",c", 3), "[c]") == 0);
    CHECK(strcmp(column("\"x\"\"y\",z", 1), "[x\"\"y]") == 0); /* "" inside a field stays doubled */
    CHECK(strcmp(column("\"x\"\"y\",z", 2), "[z]") == 0);
    CHECK(strcmp(column("a,,c", 2), "[]") == 0);
    CHECK(strcmp(column("a,b,", 3), "[]") == 0);
    CHECK(strcmp(column("a,\"\"", 2), "[]") == 0);
    /* Refused: too few columns, a quote not closed, text after a closing quote. */
    CHECK(strcmp(column("a,b", 3), "") == 0);
    CHECK(strcmp(column("a,\"[[1,2]", 2), "") == 0);
    CHECK(strcmp(column("a,\"x\"y,c", 2), "") == 0);
    CHECK(strcmp(column("a,\"x\"\"", 2), "") == 0);
    /* A broken quote after the column refuses the row too (Codex, step 12). */
    CHECK(strcmp(column("\"[[1,2]]\",\"open", 1), "") == 0);
    CHECK(strcmp(column("\"[[1,2]]\",\"x\"y", 1), "") == 0);
    CHECK(strcmp(column("\"[[1,2]]\",\"x\",z", 1), "[[[1,2]]]") == 0);
}

static long pairs_of(const char *text, double *lonlat, size_t max_pairs)
{
    return import_parse_polyline(text, strlen(text), lonlat, max_pairs);
}

static void pair_lists_parse_whole_or_not_at_all(void)
{
    double v[8];
    CHECK(pairs_of("[[-8.618643,41.141412],[-8.618499,41.141376]]", v, 4) == 2);
    CHECK(v[0] == -8.618643 && v[1] == 41.141412 && v[2] == -8.618499 && v[3] == 41.141376);
    CHECK(pairs_of(" [ [ 1 , 2 ] ,\t[3,4e1] ] ", v, 4) == 2 && v[3] == 40.0);
    CHECK(pairs_of("[]", v, 4) == 0 && pairs_of(" [ ] ", v, 4) == 0);
    CHECK(pairs_of("[[1e999,2]]", v, 4) == 1); /* a number (DESIGN §8), off the map when classified */
    /* Numbers of 63 characters are read, 64 are refused (the copy's buffer is 64 bytes, with its '\0'). */
    char text[160], digits[70];
    memset(digits, '1', sizeof digits);
    snprintf(text, sizeof text, "[[%.63s,2]]", digits);
    CHECK(pairs_of(text, v, 4) == 1);
    snprintf(text, sizeof text, "[[%.64s,2]]", digits);
    CHECK(pairs_of(text, v, 4) == -1);
    snprintf(text, sizeof text, "[[2,%.63s]]", digits);
    CHECK(pairs_of(text, v, 4) == 1);
    CHECK(pairs_of("[[1,2],[3,4]]", v, 1) == -1); /* more pairs than room: the whole row is refused */
    const char *bad[] = {"", "[", "]", "[[1,2]", "[[1,2],]", "[[1,2],,[3,4]]", "[[1],[2,3]]", "[[1,2,3]]", "[[a,2]]",
                         "[[1,2]]x", "x[[1,2]]", "[[1,2][3,4]]", "[1,2]", "[[1,2],[3,4]", "[[nan,1]]", "[[0x1,2]]",
                         "[[1 2,3]]", "[[,2]]", "[[1,]]", "[[1000000000000000000000000000000000000000000000000000000000000000000000,2]]"};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++)
        CHECK(pairs_of(bad[i], v, 4) == -1);
}

static void polyline_rows_count_each_pair_as_a_point(void)
{
    /* A header; a good trip; an empty trip; a trip with (0,0) and a place off the map; a broken list (nothing of it
     * kept, though its first pair is fine); a blank line; a short line without the column; CRLF at the end. */
    const char data[] = "TRIP,POLYLINE\n1,\"[[-8.61,41.14],[-8.62,41.15]]\"\n2,\"[]\"\n3,\"[[0,0],[200,1],[-8.6,41.1]]\"\n"
                        "4,\"[[-8.6,41.1],]\"\n\n5\n6,\"[[-8.7,41.2]]\"\r\n";
    struct import_options porto = PORTO;
    porto.polyline_col = 2;
    struct import_counts counts;
    FILE *out;
    CHECK(import_with(&porto, data, sizeof data - 1, 1, &counts, &out) == 0);
    CHECK_EQ_U64(6, counts.rows);
    CHECK_EQ_U64(6, counts.points);
    CHECK_EQ_U64(4, counts.imported);
    CHECK_EQ_U64(1, counts.skipped_zero);
    CHECK_EQ_U64(1, counts.skipped_out_of_range);
    CHECK_EQ_U64(2, counts.skipped_malformed); /* rows 4 and 5 */
    CHECK_EQ_U64(geo_code(geo_world_x(-8.61), geo_world_y(41.14)), read_code(out));
    CHECK_EQ_U64(geo_code(geo_world_x(-8.62), geo_world_y(41.15)), read_code(out));
    CHECK_EQ_U64(geo_code(geo_world_x(-8.6), geo_world_y(41.1)), read_code(out));
    CHECK_EQ_U64(geo_code(geo_world_x(-8.7), geo_world_y(41.2)), read_code(out));
    CHECK(fgetc(out) == EOF);
    fclose(out);
}

static void polyline_rows_may_be_long_up_to_their_limit(void)
{
    /* A row of exactly IMPORT_MAX_POLYLINE_LINE bytes is read (it would be malformed as a plain row), one byte more is
     * malformed, and the row after it still counts. */
    static char data[2 * IMPORT_MAX_POLYLINE_LINE + 64];
    size_t n = 0;
    for (int extra = 0; extra < 2; extra++) {
        size_t start = n;
        n += (size_t)snprintf(data + n, sizeof data - n, "1,\"[[-8.6,41.1]");
        while (n - start < IMPORT_MAX_POLYLINE_LINE + (size_t)extra - 18)
            n += (size_t)snprintf(data + n, sizeof data - n, ",[1,2]");
        while (n - start < IMPORT_MAX_POLYLINE_LINE + (size_t)extra - 2)
            data[n++] = ' ';
        n += (size_t)snprintf(data + n, sizeof data - n, "]\"\n");
        CHECK_EQ_U64(IMPORT_MAX_POLYLINE_LINE + (size_t)extra + 1, n - start); /* + its '\n' */
    }
    n += (size_t)snprintf(data + n, sizeof data - n, "2,\"[[-8.7,41.2]]\"\n");
    struct import_options porto = PORTO;
    porto.polyline_col = 2;
    struct import_counts counts;
    FILE *out;
    CHECK(import_with(&porto, data, n, 0, &counts, &out) == 0);
    fclose(out);
    CHECK_EQ_U64(3, counts.rows);
    CHECK_EQ_U64(1, counts.skipped_malformed);
    CHECK(counts.points > 100000 && counts.points == counts.imported);
}

static enum import_result gpx(const char *attributes)
{
    uint64_t code;
    return import_gpx_point(attributes, strlen(attributes), &code);
}

static void gpx_tags_need_one_good_lat_and_lon(void)
{
    uint64_t code = 0;
    const char *tag = " lat=\"39.907\" lon=\"116.391\"";
    CHECK(import_gpx_point(tag, strlen(tag), &code) == IMPORT_POINT);
    CHECK_EQ_U64(geo_code(geo_world_x(116.391), geo_world_y(39.907)), code);
    const char *good[] = {" lon='116.391' lat='39.907'", "\n  lat = \"39.9\"\n  lon = \"116.3\"\n", " lat=\"1\" lon=\"2\"/",
                          " lat=\"1\" ele='3' lon=\"2\" xmlns:x=\"a>b\""};
    for (size_t i = 0; i < sizeof good / sizeof good[0]; i++)
        CHECK(gpx(good[i]) == IMPORT_POINT);
    CHECK(gpx(" lat=\"0\" lon=\"0\"") == IMPORT_ZERO);
    CHECK(gpx(" lat=\"95\" lon=\"1\"") == IMPORT_OUT_OF_RANGE);
    const char *bad[] = {"", " lat=\"1\"", " lon=\"1\"", " lat=\"1\" lon=\"x\"", " lat=\"1\" lon=\"\"",
                         " lat=\"1\" lat=\"2\" lon=\"3\"", " lat=1 lon=2", " lat=\"1\" lon=\"2", " lat=\"1\" lon='2\"",
                         " lat=\"1\" lon=\"2\" junk", " plat=\"1\" lon=\"2\"", " lat=\"1\" lon=\"0x2\"",
                         " lat=\" 1\" lon=\"2\"", " =\"1\" lat=\"1\" lon=\"2\""};
    /* A NUL byte isn't a space (strchr would match a string's ending '\0'). */
    const char nul[] = " lat=\"1\"\0lon=\"2\"";
    CHECK(import_gpx_point(nul, sizeof nul - 1, &code) == IMPORT_MALFORMED);
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++)
        CHECK(gpx(bad[i]) == IMPORT_MALFORMED);
}

const struct check_case import_cases[] = {
    {"plain_decimals_parse_and_nothing_else_does",
     "nan, inf, hex, spaces or trailing junk accepted as a coordinate, or a NUL byte hiding junk",
     plain_decimals_parse_and_nothing_else_does},
    {"delimiters_cannot_be_part_of_a_number", "a delimiter like '.' or '-' splits numbers in half",
     delimiters_cannot_be_part_of_a_number},
    {"a_row_becomes_its_known_tile", "the CRLF left on the latitude, or the wrong columns read",
     a_row_becomes_its_known_tile},
    {"rows_are_sorted_into_the_right_bucket",
     "a bad, (0,0) or out-of-range row counted in the wrong place or kept, or strtod reading into the delimiter",
     rows_are_sorted_into_the_right_bucket},
    {"codes_are_written_as_8_little_endian_bytes", "big-endian or short codes in the .pts, so step 3 reads garbage",
     codes_are_written_as_8_little_endian_bytes},
    {"header_lines_are_skipped_before_counting", "--skip lines counted as rows, or blank header lines not skipped",
     header_lines_are_skipped_before_counting},
    {"random_files_split_into_the_same_lines_as_by_hand",
     "the line reader drops, merges or splits lines at the 1 MiB buffer edge, after a too-long line, or at the end",
     random_files_split_into_the_same_lines_as_by_hand},
    {"quoted_csv_columns_keep_their_commas",
     "a polyline column split at its own commas, a \"\" taken as the end of a field, or a broken quote read as text (step 12)",
     quoted_csv_columns_keep_their_commas},
    {"pair_lists_parse_whole_or_not_at_all",
     "half of a broken list imported, a trailing comma or a missing number accepted, or too many pairs written past the buffer",
     pair_lists_parse_whole_or_not_at_all},
    {"polyline_rows_count_each_pair_as_a_point",
     "an empty trip or a broken list counted wrong, a (0,0) or faraway pair kept, a broken list's first pair kept",
     polyline_rows_count_each_pair_as_a_point},
    {"polyline_rows_may_be_long_up_to_their_limit",
     "a long trip refused at the plain rows' 64 KB, a row past 1,000,000 bytes kept, or the row after it lost",
     polyline_rows_may_be_long_up_to_their_limit},
    {"gpx_tags_need_one_good_lat_and_lon",
     "a GPX place read from the wrong attribute (plat, ele), a doubled or missing lat kept, a broken tag taken, or a number with spaces or hex taken (step 16)",
     gpx_tags_need_one_good_lat_and_lon},
};
const size_t import_cases_count = sizeof import_cases / sizeof import_cases[0];
