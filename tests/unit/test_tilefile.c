/* Unit and random tests for src/tilefile.c (TESTING.md §9, step 3b): tile slices against slow counts
 * and against their 4 smaller tiles, code ranges with equal codes, and broken files refused. */
#include "suites.h"

#include <stdlib.h>
#include <string.h>

#include "build.h"
#include "geo.h"
#include "tilefile.h"

#define POINTS 3000

static uint64_t codes[POINTS];
static unsigned char file[BUILD_HEADER_SIZE + 8 * POINTS];

static int compare_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

static void store_le64(unsigned char *p, uint64_t value)
{
    for (int i = 0; i < 8; i++)
        p[i] = (unsigned char)(value >> (8 * i));
}

/* Header stats a build could write for n > 0 points: the whole world, at most 1 point per pixel. */
static void possible_stats(struct build_header *h, uint64_t n)
{
    memset(h, 0, sizeof *h);
    h->count = n;
    h->max_x = h->max_y = h->view_max_x = h->view_max_y = UINT32_MAX;
    for (unsigned z = 0; z <= GEO_MAX_ZOOM && n > 0; z++)
        h->max_pixel_count[z] = 1;
}

/* Sorts codes[0..n) and writes them as a .gpt into `file` (only the count matters in the header).
 * Returns the file size. */
static size_t make_gpt(size_t n)
{
    qsort(codes, n, sizeof codes[0], compare_u64);
    struct build_header h;
    possible_stats(&h, n);
    build_encode_header(&h, file);
    for (size_t i = 0; i < n; i++)
        store_le64(file + BUILD_HEADER_SIZE + 8 * i, codes[i]);
    return BUILD_HEADER_SIZE + 8 * n;
}

static uint64_t slow_count(size_t n, unsigned zoom, uint32_t x, uint32_t y)
{
    uint64_t count = 0;
    for (size_t i = 0; i < n; i++) {
        struct geo_tile t = geo_tile_of(codes[i], zoom);
        count += t.x == x && t.y == y;
    }
    return count;
}

static uint64_t tile_count(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y)
{
    uint64_t first, end;
    tilefile_tile(tf, zoom, x, y, &first, &end);
    return end - first;
}

static void a_tile_count_is_the_slow_count_and_the_sum_of_its_4_children(void)
{
    /* Clusters of random size around one spot, some exact repeats, and both corners of the world. */
    size_t n = POINTS;
    uint32_t cx = (uint32_t)check_rand(), cy = (uint32_t)check_rand();
    for (size_t i = 0; i < n - 2; i++) {
        unsigned spread = (unsigned)(check_rand() % 33);
        uint64_t r = check_rand();
        uint32_t mask = spread == 32 ? UINT32_MAX : (uint32_t)((1ull << spread) - 1);
        codes[i] = i % 5 == 0 && i > 0 ? codes[i - 1]
                                       : geo_code(cx ^ ((uint32_t)r & mask), cy ^ ((uint32_t)(r >> 32) & mask));
    }
    codes[n - 2] = 0;          /* tile 0/0 at every zoom */
    codes[n - 1] = UINT64_MAX; /* the last tile at every zoom */
    struct tilefile tf;
    CHECK(tilefile_check(file, make_gpt(n), &tf) == TILEFILE_OK);
    CHECK_EQ_U64(n, tf.header.count);
    CHECK_EQ_U64(n, tile_count(&tf, 0, 0, 0));

    for (int round = 0; round < 400; round++) {
        unsigned zoom = (unsigned)(check_rand() % (GEO_MAX_ZOOM + 1));
        struct geo_tile t;
        if (round % 4 == 3) { /* a random tile, mostly empty */
            uint32_t side_mask = zoom == 0 ? 0 : (uint32_t)((1ull << zoom) - 1);
            t.x = (uint32_t)check_rand() & side_mask;
            t.y = (uint32_t)check_rand() & side_mask;
        } else { /* the tile of a random point, the corners included */
            t = geo_tile_of(codes[round % 2 ? check_rand() % n : (size_t)(round / 4 % 2) * (n - 1)], zoom);
        }
        uint64_t count = tile_count(&tf, zoom, t.x, t.y);
        CHECK_EQ_U64(slow_count(n, zoom, t.x, t.y), count);
        if (zoom < GEO_MAX_ZOOM) {
            uint64_t children = 0;
            for (uint32_t k = 0; k < 4; k++)
                children += tile_count(&tf, zoom + 1, 2 * t.x + (k & 1), 2 * t.y + (k >> 1));
            CHECK_EQ_U64(count, children);
        }
    }
}

static void a_code_range_includes_both_ends_and_every_equal_code(void)
{
    /* 10 copies each of 100 codes spaced 1000 apart, starting at 0. */
    size_t n = 1000;
    for (size_t i = 0; i < n; i++)
        codes[i] = (uint64_t)(i % 100) * 1000;
    struct tilefile tf;
    CHECK(tilefile_check(file, make_gpt(n), &tf) == TILEFILE_OK);
    uint64_t first, end;
    tilefile_range(&tf, 5000, 5000, &first, &end);
    CHECK_EQ_U64(50, first);
    CHECK_EQ_U64(60, end);
    tilefile_range(&tf, 4001, 5999, &first, &end); /* only the 5000s */
    CHECK_EQ_U64(50, first);
    CHECK_EQ_U64(60, end);
    tilefile_range(&tf, 5001, 5999, &first, &end); /* none */
    CHECK_EQ_U64(first, end);
    tilefile_range(&tf, 0, UINT64_MAX, &first, &end);
    CHECK_EQ_U64(0, first);
    CHECK_EQ_U64(n, end);
    tilefile_range(&tf, 99000, UINT64_MAX, &first, &end); /* the last code */
    CHECK_EQ_U64(990, first);
    CHECK_EQ_U64(n, end);
    tilefile_range(&tf, 7000, 5000, &first, &end); /* low > high, the searches land 10 apart: empty, never negative */
    CHECK_EQ_U64(first, end);
    CHECK_EQ_U64(0, tilefile_code(&tf, 0));
    CHECK_EQ_U64(99000, tilefile_code(&tf, n - 1));
}

static void broken_files_are_refused_and_a_good_header_reads_back(void)
{
    struct build_header h = {3, 11, 12, 13, 14, {0}, 21, 22, 23, 24};
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        h.max_pixel_count[z] = z < 10 ? 3 : z < 20 ? 2 : 1; /* possible: 1 to 3, never growing */
    unsigned char good[BUILD_HEADER_SIZE + 24], bad[sizeof good + 8];
    build_encode_header(&h, good);
    for (int i = 0; i < 3; i++)
        store_le64(good + BUILD_HEADER_SIZE + 8 * i, 7u + (unsigned)i);
    struct tilefile tf;
    CHECK(tilefile_check(good, sizeof good, &tf) == TILEFILE_OK);
    CHECK(memcmp(&tf.header, &h, sizeof h) == 0); /* every field back where it was written */
    CHECK_EQ_U64(9, tilefile_code(&tf, 2));

    CHECK(tilefile_check(good, 0, &tf) == TILEFILE_NOT_GPT);
    CHECK(tilefile_check(good, 7, &tf) == TILEFILE_NOT_GPT);
    CHECK(tilefile_check(good, 8, &tf) == TILEFILE_CUT_SHORT);
    CHECK(tilefile_check(good, BUILD_HEADER_SIZE - 1, &tf) == TILEFILE_CUT_SHORT);
    CHECK(tilefile_check(good, sizeof good - 1, &tf) == TILEFILE_SIZE_MISMATCH); /* last point cut */
    memcpy(bad, good, sizeof good);
    CHECK(tilefile_check(bad, sizeof good + 1, &tf) == TILEFILE_SIZE_MISMATCH); /* one junk byte after it */
    CHECK(tilefile_check(bad, sizeof good + 8, &tf) == TILEFILE_SIZE_MISMATCH); /* a point too many */

    struct {
        size_t offset;
        unsigned char value;
        enum tilefile_status status;
    } cases[] = {
        {0, 'g', TILEFILE_NOT_GPT},       {7, 'X', TILEFILE_NOT_GPT},     /* label */
        {8, 2, TILEFILE_BAD_VERSION},     {11, 1, TILEFILE_BAD_VERSION},  /* version 2, 2^24 + 1 */
        {8, 0, TILEFILE_UNFINISHED},                                      /* version 0: a killed build */
        {12, 1, TILEFILE_BAD_HEADER},     {13, 2, TILEFILE_BAD_HEADER},   /* header size 257, 512 */
        {16, 2, TILEFILE_SIZE_MISMATCH},  {23, 0x20, TILEFILE_SIZE_MISMATCH}, /* count 2; 2^61 + 3: count * 8 overflows */
        {24, 14, TILEFILE_BAD_STATS},     {28, 15, TILEFILE_BAD_STATS},   /* min x > max x (13), min y > max y (14) */
        {240, 24, TILEFILE_BAD_STATS},    {244, 25, TILEFILE_BAD_STATS},  /* view box min > max */
        {40, 0, TILEFILE_BAD_STATS},      {40 + 8 * 24, 0, TILEFILE_BAD_STATS}, /* a densest pixel of 0 */
        {40, 4, TILEFILE_BAD_STATS},      {40 + 8 * 11, 3, TILEFILE_BAD_STATS}, /* more than count; growing (2 → 3) */
    };
    for (size_t c = 0; c < sizeof cases / sizeof cases[0]; c++) {
        memcpy(bad, good, sizeof good);
        bad[cases[c].offset] = cases[c].value;
        CHECK(tilefile_check(bad, sizeof good, &tf) == cases[c].status);
    }
    /* No points: every stat must be 0. */
    struct build_header empty;
    memset(&empty, 0, sizeof empty);
    build_encode_header(&empty, bad);
    CHECK(tilefile_check(bad, BUILD_HEADER_SIZE, &tf) == TILEFILE_OK);
    bad[252] = 1; /* a view box for no points */
    CHECK(tilefile_check(bad, BUILD_HEADER_SIZE, &tf) == TILEFILE_BAD_STATS);
}

const struct check_case tilefile_cases[] = {
    {"a_tile_count_is_the_slow_count_and_the_sum_of_its_4_children",
     "a tile's slice off by one at either end, x/y swapped in the tile code, or the first/last tile of the world lost",
     a_tile_count_is_the_slow_count_and_the_sum_of_its_4_children},
    {"a_code_range_includes_both_ends_and_every_equal_code",
     "the binary search stops inside a run of equal codes, drops the last code, or wraps at UINT64_MAX",
     a_code_range_includes_both_ends_and_every_equal_code},
    {"broken_files_are_refused_and_a_good_header_reads_back",
     "a wrong label, version, header size, point count or impossible stats accepted (reads past the file, divides by a 0 max), or fields read from the wrong offset",
     broken_files_are_refused_and_a_good_header_reads_back},
};
const size_t tilefile_cases_count = sizeof tilefile_cases / sizeof tilefile_cases[0];
