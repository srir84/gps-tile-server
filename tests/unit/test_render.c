/* Unit tests for src/render.c (TESTING.md §9, step 4): pixel counts for a hand-made tile, colors at known
 * points of the log scale, and a PNG taken apart chunk by chunk (CRCs, size, every pixel). */
#include "suites.h"

#include <stdlib.h>
#include <string.h>
#include <zlib.h>

#include "build.h"
#include "geo.h"
#include "render.h"
#include "tilefile.h"

static uint64_t counts[RENDER_PIXELS];

static int compare_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return x < y ? -1 : x > y;
}

/* Tile 10/843/388 (Beijing): its pixel (px, py) starts at world (843 * 256 + px, 388 * 256 + py) << 14. */
static uint64_t beijing(uint32_t px, uint32_t py, uint32_t dx, uint32_t dy)
{
    return geo_code(((843u * 256 + px) << 14) + dx, ((388u * 256 + py) << 14) + dy);
}

static void pixel_counts_of_a_hand_made_tile(void)
{
    /* 1 point at the top left, 3 at the top right, 9 at the bottom left (inside the pixel, not on its
     * corner), 2 at the bottom right's last unit, and 1 just east of the tile. */
    uint64_t codes[16] = {beijing(0, 0, 0, 0)};
    size_t n = 1;
    for (int i = 0; i < 3; i++)
        codes[n++] = beijing(255, 0, 0, 0);
    for (int i = 0; i < 9; i++)
        codes[n++] = beijing(0, 255, 5, 9);
    codes[n++] = beijing(255, 255, (1u << 14) - 1, (1u << 14) - 1);
    codes[n++] = beijing(255, 255, (1u << 14) - 1, (1u << 14) - 1);
    codes[n++] = geo_code((843u * 256 + 256) << 14, 388u * 256 << 14);
    qsort(codes, n, sizeof codes[0], compare_u64);
    static unsigned char file[BUILD_HEADER_SIZE + 8 * 16];
    struct build_header h; /* stats a build could write: the whole world, at most 1 point per pixel */
    memset(&h, 0, sizeof h);
    h.count = n;
    h.max_x = h.max_y = h.view_max_x = h.view_max_y = UINT32_MAX;
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        h.max_pixel_count[z] = 1;
    build_encode_header(&h, file);
    for (size_t i = 0; i < n; i++) {
        for (int k = 0; k < 8; k++)
            file[BUILD_HEADER_SIZE + 8 * i + (size_t)k] = (unsigned char)(codes[i] >> (8 * k));
    }
    struct tilefile tf;
    CHECK(tilefile_check(file, BUILD_HEADER_SIZE + 8 * n, &tf) == TILEFILE_OK);
    CHECK_EQ_U64(15, render_count(&tf, 10, 843, 388, counts));
    CHECK_EQ_U64(1, counts[0]);               /* (0, 0): the top left */
    CHECK_EQ_U64(3, counts[255]);             /* (255, 0): the top right */
    CHECK_EQ_U64(9, counts[255 * 256]);       /* (0, 255): the bottom left */
    CHECK_EQ_U64(2, counts[255 * 256 + 255]); /* (255, 255) */
    uint64_t total = 0;
    for (size_t i = 0; i < RENDER_PIXELS; i++)
        total += counts[i];
    CHECK_EQ_U64(15, total); /* nothing anywhere else */
    CHECK_EQ_U64(1, render_count(&tf, 10, 844, 388, counts)); /* the point east of the tile */
    CHECK_EQ_U64(1, counts[0]);
    CHECK_EQ_U64(16, render_count(&tf, 0, 0, 0, counts)); /* zoom 0: all of them, in one pixel */
}

static void colors_follow_the_log_scale(void)
{
    struct {
        uint64_t count;
        uint64_t max;
        unsigned char rgba[4];
    } cases[] = {
        {0, 100, {0, 0, 0, 0}},                            /* empty: transparent */
        {1, 100, {0x8c, 0x29, 0x81, 255}},                 /* t = 0: the bottom color, still opaque */
        {10, 10000, {0xb7, 0x37, 0x79, 255}},              /* t = 1/4: the second stop */
        {10, 100, {0xde, 0x49, 0x68, 255}},                /* t = 1/2: the middle stop */
        {1000, 10000, {0xfe, 0x9f, 0x6d, 255}},            /* t = 3/4 */
        {100, 100, {0xfc, 0xfd, 0xbf, 255}},               /* t = 1: the densest pixel gets the top color */
        {500, 100, {0xfc, 0xfd, 0xbf, 255}},               /* more than the header's max: stays at the top */
        {1, 1, {0xfc, 0xfd, 0xbf, 255}},                   /* max 1: every point is the densest */
        {1, 0, {0xfc, 0xfd, 0xbf, 255}},                   /* a header that says 0: no division by log(0) */
        {UINT32_MAX, UINT64_MAX, {0xde, 0x49, 0x68, 255}}, /* ln(2^32) / ln(2^64): t = 1/2, no overflow */
        {8, 256, {203, 64, 113, 255}}, /* t = 3/8, halfway between 2 stops: 202.5 and 112.5 round up */
        {1ull << 33, 1ull << 33, {0xfc, 0xfd, 0xbf, 255}}, /* 8 billion points: still the top color (no 32-bit cap) */
        {1ull << 32, 1ull << 34, {252, 231, 172, 255}},    /* t = 32/34; a 32-bit count would be 0: transparent */
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        unsigned char c[4];
        render_color(cases[i].count, cases[i].max, c);
        CHECK(memcmp(c, cases[i].rgba, 4) == 0);
    }
    uint64_t points;
    unsigned char *png = NULL;
    size_t size;
    struct tilefile none = {0};
    CHECK(render_tile(&none, GEO_MAX_ZOOM + 1, 0, 0, &png, &size, &points) == -1); /* no tile there: refused */
    CHECK(render_tile(&none, 3, 8, 0, &png, &size, &points) == -1);
    CHECK(render_tile(&none, 3, 0, 8, &png, &size, &points) == -1);
    CHECK(png == NULL);
}

static uint32_t be32(const unsigned char *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static void a_png_has_valid_chunks_and_every_pixel(void)
{
    memset(counts, 0, sizeof counts);
    counts[0] = 1;
    counts[256 + 7] = 50;
    counts[RENDER_PIXELS - 1] = 2500;
    unsigned char *png;
    size_t size;
    CHECK(render_png(counts, 2500, &png, &size) == 0);
    static const unsigned char signature[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    int ok = size > 8 + 25 + 12 + 12 && memcmp(png, signature, 8) == 0;
    /* Chunks: IHDR (13 bytes), IDAT, IEND (0 bytes), each with a CRC over its type and data. */
    size_t at = 8, chunks = 0;
    unsigned char *pixels = malloc(256 * 1025);
    uLongf pixels_size = 256 * 1025;
    int ihdr_ok = 0, idat_ok = 0, iend_ok = 0;
    while (ok && pixels != NULL && at + 12 <= size) {
        uint32_t length = be32(png + at);
        const unsigned char *type = png + at + 4, *data = png + at + 8;
        if (at + 12 + length > size || be32(data + length) != (uint32_t)crc32(0, type, length + 4)) {
            ok = 0;
            break;
        }
        if (chunks == 0 && memcmp(type, "IHDR", 4) == 0 && length == 13)
            ihdr_ok = be32(data) == 256 && be32(data + 4) == 256 && data[8] == 8 && data[9] == 6 && data[10] == 0 &&
                      data[11] == 0 && data[12] == 0;
        if (memcmp(type, "IDAT", 4) == 0)
            idat_ok = uncompress(pixels, &pixels_size, data, length) == Z_OK && pixels_size == 256 * 1025;
        if (memcmp(type, "IEND", 4) == 0)
            iend_ok = length == 0 && at + 12 == size;
        at += 12 + length;
        chunks++;
    }
    free(png);
    CHECK(ok && ihdr_ok && idat_ok && iend_ok && chunks == 3);
    for (size_t py = 0; py < 256; py++) {
        CHECK_EQ_U64(0, pixels[py * 1025]); /* row filter: none */
        for (size_t px = 0; px < 256; px++) {
            unsigned char want[4];
            render_color(counts[py * 256 + px], 2500, want);
            CHECK(memcmp(pixels + py * 1025 + 1 + 4 * px, want, 4) == 0);
        }
    }
    free(pixels);
}

const struct check_case render_cases[] = {
    {"pixel_counts_of_a_hand_made_tile",
     "x/y swapped, a pixel off by one, the bottom row drawn at the top, or a point of the next tile drawn in this one",
     pixel_counts_of_a_hand_made_tile},
    {"colors_follow_the_log_scale",
     "a linear scale, stops out of order, halves rounded to even, an empty pixel drawn opaque, log(0) for a max of 0 or 1, counts cut to 32 bits, or a tile outside the world drawn",
     colors_follow_the_log_scale},
    {"a_png_has_valid_chunks_and_every_pixel",
     "a wrong CRC, chunk length or IHDR field (browsers reject the tile), or pixels shifted by the row filter byte",
     a_png_has_valid_chunks_and_every_pixel},
};
const size_t render_cases_count = sizeof render_cases / sizeof render_cases[0];
