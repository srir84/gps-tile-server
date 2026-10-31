/* Unit and random tests for src/area.c (TESTING.md §9, step 7): box counts and box points against a slow
 * check of every point, for random boxes, boxes on square edges and pixel-sized boxes, and bbox parsing. */
#include "suites.h"

#include <stdlib.h>
#include <string.h>

#include "area.h"
#include "build.h"
#include "geo.h"

#define POINTS 4000

static uint64_t codes[POINTS];
static unsigned char file[BUILD_HEADER_SIZE + 8 * POINTS];

static int compare_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

/* Clustered random points (with repeats and both world corners), sorted into a .gpt in `file`. */
static void make_points(struct tilefile *tf)
{
    uint32_t cx = (uint32_t)check_rand(), cy = (uint32_t)check_rand();
    for (size_t i = 0; i < POINTS; i++) {
        unsigned spread = (unsigned)(check_rand() % 33);
        uint64_t r = check_rand();
        uint32_t mask = spread == 32 ? UINT32_MAX : (uint32_t)((1ull << spread) - 1);
        codes[i] = i % 6 == 0 && i > 0 ? codes[i - 1] : geo_code(cx ^ ((uint32_t)r & mask), cy ^ ((uint32_t)(r >> 32) & mask));
    }
    codes[0] = 0;
    codes[1] = UINT64_MAX;
    qsort(codes, POINTS, sizeof codes[0], compare_u64);
    struct build_header h; /* stats a build could write: the whole world, at most 1 point per pixel */
    memset(&h, 0, sizeof h);
    h.count = POINTS;
    h.max_x = h.max_y = h.view_max_x = h.view_max_y = UINT32_MAX;
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        h.max_pixel_count[z] = 1;
    build_encode_header(&h, file);
    for (size_t i = 0; i < POINTS; i++) {
        for (int k = 0; k < 8; k++)
            file[BUILD_HEADER_SIZE + 8 * i + (size_t)k] = (unsigned char)(codes[i] >> (8 * k));
    }
    tilefile_check(file, sizeof file, tf);
}

static int inside(uint64_t code, const struct area_box *b)
{
    uint32_t x, y;
    geo_split(code, &x, &y);
    return x >= b->x0 && x <= b->x1 && y >= b->y0 && y <= b->y1;
}

struct collected {
    uint64_t codes[POINTS];
    size_t n;
    size_t stop_after; /* emit returns 1 after this many */
};

/* Keeps an emitted point. More points than exist (a broken walk) stop the walk, for the counts to show it. */
static int collect(uint32_t x, uint32_t y, void *context)
{
    struct collected *c = context;
    if (c->n == POINTS)
        return 1;
    c->codes[c->n++] = geo_code(x, y);
    return c->n == c->stop_after;
}

static uint32_t add_clamped(uint32_t a, uint32_t b)
{
    return b > UINT32_MAX - a ? UINT32_MAX : a + b;
}

/* A box: random, exactly one Z-order square, a square shifted by one unit, or one pixel. */
static struct area_box random_box(int kind)
{
    uint32_t x, y;
    geo_split(codes[check_rand() % POINTS], &x, &y);
    unsigned level = (unsigned)(check_rand() % 33);
    uint32_t span = (uint32_t)((UINT64_C(1) << (32 - level)) - 1); /* a square's last unit, from its corner */
    struct area_box b;
    if (kind == 0) { /* random size, near a point */
        b.x0 = x - (x < span / 2 ? x : span / 2);
        b.y0 = y - (y < span / 3 ? y : span / 3);
        b.x1 = add_clamped(b.x0, span);
        b.y1 = add_clamped(b.y0, span / 2);
    } else if (kind == 1) { /* exactly one square: its edges are where slices split */
        b.x0 = x & ~span;
        b.y0 = y & ~span;
        b.x1 = b.x0 + span;
        b.y1 = b.y0 + span;
    } else if (kind == 2) { /* a square moved one unit east and south: edge squares on every side */
        b.x0 = add_clamped(x & ~span, 1);
        b.y0 = add_clamped(y & ~span, 1);
        b.x1 = add_clamped(b.x0, span);
        b.y1 = add_clamped(b.y0, span);
    } else { /* a pixel at a random zoom, its own units from first to last: what hovering asks for */
        unsigned shift = 24 - (unsigned)(check_rand() % (GEO_MAX_ZOOM + 1));
        b.x0 = x >> shift << shift;
        b.y0 = y >> shift << shift;
        b.x1 = b.x0 + (((uint32_t)1 << shift) - 1);
        b.y1 = b.y0 + (((uint32_t)1 << shift) - 1);
    }
    return b;
}

static void box_count_and_points_equal_a_slow_check_of_every_point(void)
{
    struct tilefile tf;
    make_points(&tf);
    static struct collected got;
    for (int round = 0; round < 600; round++) {
        struct area_box b = random_box(round % 4);
        uint64_t slow = 0;
        for (size_t i = 0; i < POINTS; i++)
            slow += (uint64_t)inside(codes[i], &b);
        CHECK_EQ_U64(slow, area_count(&tf, &b));
        got.n = 0;
        got.stop_after = 0;
        CHECK_EQ_U64(slow, area_points(&tf, &b, UINT64_MAX, collect, &got));
        CHECK_EQ_U64(slow, got.n);
        size_t k = 0;
        for (size_t i = 0; i < POINTS; i++) { /* the same points, in file order */
            if (inside(codes[i], &b))
                CHECK_EQ_U64(codes[i], got.codes[k++]);
        }
        if (slow > 2) { /* a limit, and a receiver that stops early */
            got.n = 0;
            CHECK_EQ_U64(slow / 2, area_points(&tf, &b, slow / 2, collect, &got));
            CHECK_EQ_U64(slow / 2, got.n);
            got.n = 0;
            got.stop_after = 2;
            CHECK_EQ_U64(1, area_points(&tf, &b, UINT64_MAX, collect, &got));
            CHECK_EQ_U64(2, got.n);
        }
    }
    struct area_box world = {.x0 = 0, .y0 = 0, .x1 = UINT32_MAX, .y1 = UINT32_MAX};
    CHECK_EQ_U64(POINTS, area_count(&tf, &world));
}

static void bbox_text_is_checked_and_turned_into_world_units(void)
{
    struct area_box b;
    const char *why;
    CHECK(area_parse_bbox("-180,-85.05112877980659,180,85.05112877980659", &b, &why) == 0);
    CHECK(b.x0 == 0 && b.y0 == 0 && b.x1 == UINT32_MAX && b.y1 == UINT32_MAX); /* east edge 180 = the last unit */
    CHECK(area_parse_bbox("116.3,39.9,116.4,40", &b, &why) == 0);
    CHECK(b.x0 == geo_world_x(116.3) && b.x1 == geo_world_x(116.4));
    CHECK(b.y0 == geo_world_y(40) && b.y1 == geo_world_y(39.9)); /* north is the smaller y */
    CHECK(area_parse_bbox("1,2,1,2", &b, &why) == 0);           /* a single point is a box */
    const char *bad[] = {"",           "1,2,3",         "1,2,3,4,5",      "1,2,3,",      ",1,2,3",
                         "1,,2,3",     "a,2,3,4",       "nan,2,3,4",      "1,2,inf,4",   "1e999,2,3,4",
                         " 1,2,3,4",   "1,2,3,4 ",      "0x1,2,3,4",      "-181,0,0,1",  "0,-86,1,0",
                         "0,0,180.1,1", "0,0,1,85.06",  "2,0,1,1",        "0,2,1,1",     "1;2;3;4"};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++)
        CHECK(area_parse_bbox(bad[i], &b, &why) != 0 && why != NULL);
}

const struct check_case area_cases[] = {
    {"box_count_and_points_equal_a_slow_check_of_every_point",
     "a point on a box edge or a square edge lost or counted twice, an edge square counted whole, or export rows out of order or past the limit",
     box_count_and_points_equal_a_slow_check_of_every_point},
    {"bbox_text_is_checked_and_turned_into_world_units",
     "west > east, NaN, infinity or an out-of-range bbox accepted; north/south swapped; lon 180 as an east edge wrapping to x = 0",
     bbox_text_is_checked_and_turned_into_world_units},
};
const size_t area_cases_count = sizeof area_cases / sizeof area_cases[0];
