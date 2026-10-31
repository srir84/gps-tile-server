/* render.c: tile drawing declared in render.h (DESIGN §5.5). */
#include "render.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

#include "geo.h"

/* Magenta → pink → red → orange → pale yellow, evenly spaced from t = 0 to t = 1 (the bright half of the
 * "magma" scale: even a single point stays visible on a dark base map). */
static const unsigned char STOPS[5][3] = {
    {0x8c, 0x29, 0x81}, {0xb7, 0x37, 0x79}, {0xde, 0x49, 0x68}, {0xfe, 0x9f, 0x6d}, {0xfc, 0xfd, 0xbf},
};

uint64_t render_count(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y, uint64_t counts[RENDER_PIXELS])
{
    memset(counts, 0, RENDER_PIXELS * sizeof counts[0]);
    uint64_t first, end;
    tilefile_tile(tf, zoom, x, y, &first, &end);
    unsigned shift = 24 - zoom; /* a pixel is 2^(32 - zoom - 8) world units wide */
    for (uint64_t i = first; i < end; i++) {
        uint32_t wx, wy;
        geo_split(tilefile_code(tf, i), &wx, &wy);
        counts[((wy >> shift) & 0xFF) << 8 | ((wx >> shift) & 0xFF)]++; /* 64-bit: billions of points fit */
    }
    return end - first;
}

void render_color(uint64_t count, uint64_t max, unsigned char rgba[4])
{
    if (count == 0) {
        memset(rgba, 0, 4);
        return;
    }
    double t = max <= 1 ? 1.0 : log((double)count) / log((double)max);
    double position = (t < 0.0 ? 0.0 : t < 1.0 ? t : 1.0) * 4.0; /* stays on the scale whatever the header says */
    int stop = position >= 4.0 ? 3 : (int)position;
    double f = position - stop;
    for (int k = 0; k < 3; k++)
        rgba[k] = (unsigned char)lround(STOPS[stop][k] + (STOPS[stop + 1][k] - STOPS[stop][k]) * f);
    rgba[3] = 255;
}

static void store_be32(unsigned char *p, uint32_t value)
{
    for (int i = 0; i < 4; i++)
        p[i] = (unsigned char)(value >> (24 - 8 * i));
}

/* Writes one PNG chunk (length, type, data, CRC of type + data) at p. Returns the bytes written. */
static size_t put_chunk(unsigned char *p, const char *type, const unsigned char *data, uint32_t length)
{
    store_be32(p, length);
    memcpy(p + 4, type, 4);
    if (length > 0)
        memcpy(p + 8, data, length);
    store_be32(p + 8 + length, (uint32_t)crc32(0, p + 4, length + 4));
    return 12 + (size_t)length;
}

int render_png(const uint64_t counts[RENDER_PIXELS], uint64_t max, unsigned char **png, size_t *size)
{
    /* Each row is a filter byte (0: none) then 256 RGBA pixels. */
    const size_t row = 1 + 4 * RENDER_SIDE, raw_size = row * RENDER_SIDE;
    unsigned char *raw = malloc(raw_size);
    uLongf packed_size = compressBound((uLong)raw_size);
    unsigned char *out = malloc(8 + 25 + 12 + packed_size + 12);
    if (raw == NULL || out == NULL) {
        free(raw);
        free(out);
        return -1;
    }
    for (size_t py = 0; py < RENDER_SIDE; py++) {
        raw[py * row] = 0;
        for (size_t px = 0; px < RENDER_SIDE; px++)
            render_color(counts[py * RENDER_SIDE + px], max, raw + py * row + 1 + 4 * px);
    }
    /* The compressed data goes straight into the IDAT chunk's place, after its 8-byte start. */
    static const unsigned char signature[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    unsigned char ihdr[13] = {0};
    store_be32(ihdr, RENDER_SIDE);
    store_be32(ihdr + 4, RENDER_SIDE);
    ihdr[8] = 8; /* bits per channel */
    ihdr[9] = 6; /* RGBA; compression, filter and interlace methods stay 0 */
    memcpy(out, signature, 8);
    size_t n = 8 + put_chunk(out + 8, "IHDR", ihdr, sizeof ihdr);
    int status = compress2(out + n + 8, &packed_size, raw, (uLong)raw_size, Z_DEFAULT_COMPRESSION);
    free(raw);
    if (status != Z_OK) {
        free(out);
        return -1;
    }
    store_be32(out + n, (uint32_t)packed_size);
    memcpy(out + n + 4, "IDAT", 4);
    store_be32(out + n + 8 + packed_size, (uint32_t)crc32(0, out + n + 4, (uInt)packed_size + 4));
    n += 12 + packed_size;
    n += put_chunk(out + n, "IEND", NULL, 0);
    *png = out;
    *size = n;
    return 0;
}

int render_tile(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y, unsigned char **png, size_t *size,
                uint64_t *points)
{
    if (zoom > GEO_MAX_ZOOM || (uint64_t)x >> zoom != 0 || (uint64_t)y >> zoom != 0)
        return -1; /* callers check first; this keeps a bad tile from reading past max_pixel_count */
    uint64_t *counts = malloc(RENDER_PIXELS * sizeof *counts); /* 512 KB: too big for a thread's stack */
    if (counts == NULL)
        return -1;
    *points = render_count(tf, zoom, x, y, counts);
    int status = render_png(counts, tf->header.max_pixel_count[zoom], png, size);
    free(counts);
    return status;
}
