/* Unit and random tests for src/build.c (TESTING.md §9, step 3a): the merge sort against a plain
 * qsort, with chunks small enough to force many runs, and the header against slow counts. */
#define _POSIX_C_SOURCE 200809L /* pipe, read, close with -std=c11 */
#include "suites.h"

#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "build.h"
#include "geo.h"

#define MAX_CODES 20002

static uint64_t codes[MAX_CODES], sorted_codes[MAX_CODES];

static FILE *pts_file(const uint64_t *values, size_t n)
{
    FILE *f = tmpfile();
    for (size_t i = 0; f != NULL && i < n; i++) {
        unsigned char b[8];
        for (int k = 0; k < 8; k++)
            b[k] = (unsigned char)(values[i] >> (8 * k));
        fwrite(b, 1, 8, f);
    }
    if (f != NULL)
        rewind(f);
    return f;
}

static uint64_t le64(const unsigned char *b)
{
    uint64_t value = 0;
    for (int i = 7; i >= 0; i--)
        value = (value << 8) | b[i];
    return value;
}

static uint32_t le32(const unsigned char *b)
{
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24;
}

/* Builds `n` codes split over `files` inputs, sorting `chunk` codes at a time. On BUILD_OK, *out is
 * the .gpt, rewound. */
static enum build_status build_codes(const uint64_t *values, size_t n, size_t files, size_t chunk,
                                     struct build_header *header, size_t *runs_used, FILE **out)
{
    FILE *runs = tmpfile();
    *out = tmpfile();
    struct build *b = runs != NULL && *out != NULL ? build_start(chunk, runs) : NULL;
    enum build_status status = b != NULL ? BUILD_OK : BUILD_NO_MEMORY;
    for (size_t k = 0; k < files && status == BUILD_OK; k++) {
        size_t from = n * k / files, to = n * (k + 1) / files;
        FILE *in = pts_file(values + from, to - from);
        status = in != NULL ? build_add(b, in) : BUILD_READ_ERROR;
        if (in != NULL)
            fclose(in);
    }
    if (status == BUILD_OK)
        status = build_finish(b, *out, header, runs_used);
    build_free(b);
    if (runs != NULL)
        fclose(runs);
    if (*out != NULL)
        rewind(*out);
    return status;
}

static int compare_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

static void random_codes_sort_the_same_with_any_chunk_size(void)
{
    /* Half fully random, half from a small pool (many equal codes), plus both extremes. */
    size_t n = MAX_CODES;
    for (size_t i = 0; i < n - 2; i++)
        codes[i] = i % 2 ? check_rand() : check_rand() % 50 * 0x9E3779B97F4A7C15u;
    codes[n - 2] = 0;
    codes[n - 1] = UINT64_MAX;
    memcpy(sorted_codes, codes, sizeof codes);
    qsort(sorted_codes, n, sizeof sorted_codes[0], compare_u64);

    static unsigned char first[256 + 8 * MAX_CODES], got[256 + 8 * MAX_CODES];
    const size_t chunks[] = {1 << 20, n, 6007, 1000, 79}; /* 79 → 254 runs, just under the limit */
    for (size_t c = 0; c < sizeof chunks / sizeof chunks[0]; c++) {
        struct build_header header;
        size_t runs;
        FILE *out;
        CHECK(build_codes(codes, n, 1 + c, chunks[c], &header, &runs, &out) == BUILD_OK);
        CHECK_EQ_U64((n + chunks[c] - 1) / chunks[c], runs);
        size_t size = fread(got, 1, sizeof got, out);
        fclose(out);
        CHECK_EQ_U64(256 + 8 * n, size);
        CHECK_EQ_U64(n, le64(got + 16));
        for (size_t i = 0; i < n; i++)
            CHECK_EQ_U64(sorted_codes[i], le64(got + 256 + 8 * i));
        if (c == 0)
            memcpy(first, got, size);
        CHECK(memcmp(first, got, size) == 0); /* the header too: same file whatever the chunk size */
    }
}

/* Random points in clusters of several sizes, so pixels are shared at many zooms. */
#define STAT_POINTS 1500
static uint32_t xs[STAT_POINTS], ys[STAT_POINTS];

static int compare_u32(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return x < y ? -1 : x > y;
}

static void header_stats_match_slow_counts(void)
{
    size_t n = STAT_POINTS;
    uint32_t cx = (uint32_t)check_rand(), cy = (uint32_t)check_rand();
    for (size_t i = 0; i < n; i++) {
        unsigned spread = (unsigned)(check_rand() % 33); /* cluster size: 1 to 2^32 world units */
        uint64_t r = check_rand();
        uint32_t mask = spread == 32 ? UINT32_MAX : (uint32_t)((1ull << spread) - 1);
        xs[i] = i % 7 == 0 && i > 0 ? xs[i - 1] : cx ^ ((uint32_t)r & mask); /* some exact repeats */
        ys[i] = i % 7 == 0 && i > 0 ? ys[i - 1] : cy ^ ((uint32_t)(r >> 32) & mask);
        codes[i] = geo_code(xs[i], ys[i]);
    }
    struct build_header h;
    size_t runs;
    FILE *out;
    CHECK(build_codes(codes, n, 2, 100, &h, &runs, &out) == BUILD_OK);
    fclose(out);
    CHECK_EQ_U64(n, h.count);

    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++) {
        /* Slow count: for every point, how many points share its pixel (a zoom z + 8 tile). */
        uint64_t most = 0;
        for (size_t i = 0; i < n; i++) {
            struct geo_tile a = geo_tile_of(codes[i], z + 8 > GEO_MAX_ZOOM ? GEO_MAX_ZOOM : z + 8);
            uint64_t same = 0;
            for (size_t j = 0; j < n; j++) {
                if (z + 8 > GEO_MAX_ZOOM) { /* finer than a zoom 24 tile: compare x and y directly */
                    same += (xs[j] >> (24 - z)) == (xs[i] >> (24 - z)) && (ys[j] >> (24 - z)) == (ys[i] >> (24 - z));
                } else {
                    struct geo_tile b = geo_tile_of(codes[j], z + 8);
                    same += a.x == b.x && a.y == b.y;
                }
            }
            most = same > most ? same : most;
        }
        CHECK_EQ_U64(most, h.max_pixel_count[z]);
    }

    qsort(xs, n, sizeof xs[0], compare_u32);
    qsort(ys, n, sizeof ys[0], compare_u32);
    CHECK_EQ_U64(xs[0], h.min_x);
    CHECK_EQ_U64(ys[0], h.min_y);
    CHECK_EQ_U64(xs[n - 1], h.max_x);
    CHECK_EQ_U64(ys[n - 1], h.max_y);
    size_t cut = n / 100; /* the 16th smallest and 16th largest, widened to 65,536-unit buckets */
    CHECK_EQ_U64(xs[cut] & 0xFFFF0000u, h.view_min_x);
    CHECK_EQ_U64(ys[cut] & 0xFFFF0000u, h.view_min_y);
    CHECK_EQ_U64(xs[n - 1 - cut] | 0xFFFFu, h.view_max_x);
    CHECK_EQ_U64(ys[n - 1 - cut] | 0xFFFFu, h.view_max_y);
}

static void a_known_set_of_points_gives_a_known_header(void)
{
    /* 5 points on one spot and 1 far away: in different pixels even at zoom 0. */
    uint64_t a = geo_code(0x12345678u, 0x9ABCDEF0u), far = geo_code(0xF0000000u, 0x00000010u);
    uint64_t values[6] = {a, far, a, a, a, a};
    struct build_header h;
    size_t runs;
    FILE *out;
    CHECK(build_codes(values, 6, 1, 4, &h, &runs, &out) == BUILD_OK);
    unsigned char bytes[256 + 48];
    size_t size = fread(bytes, 1, sizeof bytes, out);
    fclose(out);
    CHECK_EQ_U64(256 + 48, size);
    CHECK_EQ_U64(2, runs);
    CHECK_EQ_U64(6, h.count);
    CHECK_EQ_U64(0x12345678u, h.min_x);
    CHECK_EQ_U64(0x00000010u, h.min_y);
    CHECK_EQ_U64(0xF0000000u, h.max_x);
    CHECK_EQ_U64(0x9ABCDEF0u, h.max_y);
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        CHECK_EQ_U64(5, h.max_pixel_count[z]);
    /* 6 points: 1% of 6 is 0, so the view box is the bounds widened to whole buckets. */
    CHECK_EQ_U64(0x12340000u, h.view_min_x);
    CHECK_EQ_U64(0x00000000u, h.view_min_y);
    CHECK_EQ_U64(0xF000FFFFu, h.view_max_x);
    CHECK_EQ_U64(0x9ABCFFFFu, h.view_max_y);
    CHECK(far < a); /* the top bit of a code is y's top bit: far has the smaller y */
    CHECK_EQ_U64(far, le64(bytes + 256));
    for (int i = 1; i < 6; i++)
        CHECK_EQ_U64(a, le64(bytes + 256 + 8 * i));
}

static void header_fields_sit_at_their_documented_offsets(void)
{
    struct build_header h = {0x0102030405060708u, 11, 12, 13, 14, {0}, 21, 22, 23, 24};
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        h.max_pixel_count[z] = 1000 + z;
    unsigned char b[BUILD_HEADER_SIZE];
    build_encode_header(&h, b);
    CHECK(memcmp(b, "GPSTILE\0", 8) == 0);
    CHECK_EQ_U64(1, le32(b + 8));
    CHECK_EQ_U64(256, le32(b + 12));
    CHECK(b[16] == 0x08 && b[23] == 0x01); /* little-endian */
    CHECK_EQ_U64(0x0102030405060708u, le64(b + 16));
    CHECK_EQ_U64(11, le32(b + 24));
    CHECK_EQ_U64(12, le32(b + 28));
    CHECK_EQ_U64(13, le32(b + 32));
    CHECK_EQ_U64(14, le32(b + 36));
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        CHECK_EQ_U64(1000 + z, le64(b + 40 + 8 * z));
    CHECK_EQ_U64(21, le32(b + 240));
    CHECK_EQ_U64(22, le32(b + 244));
    CHECK_EQ_U64(23, le32(b + 248));
    CHECK_EQ_U64(24, le32(b + 252));
}

static void more_than_256_runs_is_refused(void)
{
    for (size_t i = 0; i < 257; i++)
        codes[i] = check_rand();
    struct build_header h;
    size_t runs;
    FILE *out;
    CHECK(build_codes(codes, 256, 3, 1, &h, &runs, &out) == BUILD_OK);
    fclose(out);
    CHECK_EQ_U64(256, runs);
    CHECK(build_codes(codes, 257, 3, 1, &h, &runs, &out) == BUILD_TOO_MANY_RUNS);
    fclose(out);
}

static void a_partial_code_is_refused_and_no_points_give_just_the_header(void)
{
    FILE *runs = tmpfile(), *in = tmpfile(), *out;
    CHECK(runs != NULL && in != NULL);
    fwrite("12345678abcd", 1, 12, in); /* one code and half of another */
    rewind(in);
    struct build *b = build_start(16, runs);
    CHECK(b != NULL);
    enum build_status status = build_add(b, in);
    build_free(b);
    fclose(in);
    fclose(runs);
    CHECK(status == BUILD_BAD_INPUT);

    struct build_header h;
    size_t used;
    CHECK(build_codes(codes, 0, 1, 16, &h, &used, &out) == BUILD_OK);
    unsigned char bytes[300];
    size_t size = fread(bytes, 1, sizeof bytes, out);
    fclose(out);
    CHECK_EQ_U64(256, size);
    CHECK_EQ_U64(0, used);
    CHECK(memcmp(bytes, "GPSTILE\0", 8) == 0);
    for (size_t i = 16; i < 256; i++)
        CHECK_EQ_U64(0, bytes[i]);
}

/* Adds a stream holding `n` bytes to b. */
static enum build_status add_bytes(struct build *b, const unsigned char *bytes, size_t n)
{
    FILE *in = tmpfile();
    if (in == NULL)
        return BUILD_READ_ERROR;
    fwrite(bytes, 1, n, in);
    rewind(in);
    enum build_status status = build_add(b, in);
    fclose(in);
    return status;
}

static void a_gpt_given_as_input_is_refused(void)
{
    struct build_header h;
    memset(&h, 0, sizeof h);
    unsigned char header[BUILD_HEADER_SIZE];
    build_encode_header(&h, header);
    FILE *runs = tmpfile();
    CHECK(runs != NULL);
    struct build *b = build_start(2, runs);
    CHECK(b != NULL);
    /* One code from an earlier input leaves room for one more in the chunk: the .gpt must still be seen. */
    enum build_status first = add_bytes(b, (const unsigned char *)"12345678", 8);
    enum build_status finished = add_bytes(b, header, sizeof header);
    header[8] = 0; /* version 0: the header of a build that was killed before it finished */
    enum build_status unfinished = add_bytes(b, header, sizeof header);
    header[8] = 2; /* version 2: not a header this program writes, so only the label matches */
    enum build_status other = add_bytes(b, header, sizeof header);
    build_free(b);
    fclose(runs);
    CHECK(first == BUILD_OK);
    CHECK(finished == BUILD_GPT_INPUT);
    CHECK(unfinished == BUILD_GPT_INPUT);
    CHECK(other == BUILD_OK);
}

static void an_unfinished_gpt_says_so_until_its_header_is_written(void)
{
    /* Writing the final header needs a seek. A pipe can't seek, so the build stops just before it, the
     * way a killed build does, and what was written can be read back. */
    int ends[2];
    CHECK(pipe(ends) == 0);
    FILE *out = fdopen(ends[1], "wb"), *runs = tmpfile();
    CHECK(out != NULL && runs != NULL);
    struct build *b = build_start(16, runs);
    CHECK(b != NULL);
    uint64_t values[3] = {3, 1, 2};
    unsigned char bytes[24];
    for (size_t i = 0; i < 24; i++)
        bytes[i] = (unsigned char)(values[i / 8] >> (8 * (i % 8)));
    struct build_header h;
    size_t used;
    CHECK(add_bytes(b, bytes, sizeof bytes) == BUILD_OK);
    enum build_status status = build_finish(b, out, &h, &used);
    build_free(b);
    fclose(runs);
    fclose(out);
    unsigned char got[BUILD_HEADER_SIZE + 24];
    ssize_t n = read(ends[0], got, sizeof got);
    close(ends[0]);
    CHECK(status == BUILD_WRITE_ERROR);
    CHECK_EQ_U64(sizeof got, (uint64_t)n);
    CHECK(memcmp(got, "GPSTILE\0", 8) == 0);
    CHECK_EQ_U64(0, le32(got + 8)); /* version 0: unfinished */
    CHECK_EQ_U64(256, le32(got + 12));
    CHECK(build_is_gpt(got));
    CHECK_EQ_U64(1, le64(got + 256)); /* the sorted points follow */
}

const struct check_case build_cases[] = {
    {"random_codes_sort_the_same_with_any_chunk_size",
     "the merge drops, repeats or misorders codes across runs, at run ends, or on equal codes; or the file depends on --mem",
     random_codes_sort_the_same_with_any_chunk_size},
    {"header_stats_match_slow_counts",
     "the densest pixel counted at the tile instead of the pixel, or split across runs; wrong bounds or view box",
     header_stats_match_slow_counts},
    {"a_known_set_of_points_gives_a_known_header", "header fields swapped (x/y, min/max) or the view box not widened",
     a_known_set_of_points_gives_a_known_header},
    {"header_fields_sit_at_their_documented_offsets", "a header field at the wrong offset or big-endian, so step 3b reads garbage",
     header_fields_sit_at_their_documented_offsets},
    {"more_than_256_runs_is_refused", "run 257 written past the end of the run table",
     more_than_256_runs_is_refused},
    {"a_partial_code_is_refused_and_no_points_give_just_the_header",
     "a .pts cut mid-code silently dropped, or an empty input crashing or writing junk",
     a_partial_code_is_refused_and_no_points_give_just_the_header},
    {"a_gpt_given_as_input_is_refused",
     "a .gpt or a killed build's leftover read as points (its header becomes 32 junk points), also when it starts with one code of room left in the chunk",
     a_gpt_given_as_input_is_refused},
    {"an_unfinished_gpt_says_so_until_its_header_is_written",
     "a killed build's leftover starting with 256 zero bytes, which a later build takes in as points (Claude step 3a round 2)",
     an_unfinished_gpt_says_so_until_its_header_is_written},
};
const size_t build_cases_count = sizeof build_cases / sizeof build_cases[0];
