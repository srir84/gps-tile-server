/* render.h: draws one map tile (DESIGN §5.5): counts the points in each of its 256 × 256 pixels, colors
 * each count on a log scale fixed per zoom (the densest pixel in the .gpt header = the top color), and
 * encodes the picture as a PNG with zlib. An empty pixel is transparent. */
#ifndef RENDER_H
#define RENDER_H

#include <stddef.h>
#include <stdint.h>

#include "tilefile.h"

#define RENDER_SIDE 256
#define RENDER_PIXELS (RENDER_SIDE * RENDER_SIDE)

/* counts[py * 256 + px] = the points of tile zoom/x/y in pixel (px, py), px to the east, py to the south.
 * Returns the points in the tile. The tile must exist: zoom ≤ GEO_MAX_ZOOM,
 * x and y < 2^zoom (render_tile checks it). */
uint64_t render_count(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y, uint64_t counts[RENDER_PIXELS]);

/* The color of a pixel with `count` points when the densest pixel at its zoom has `max` points:
 * t = ln(count) / ln(max) (1 if max ≤ 1, at most 1), mapped from magenta (t = 0) to pale yellow
 * (t = 1) through 5 evenly spaced color stops, each channel rounded half up. Opaque; count 0 → fully
 * transparent. */
void render_color(uint64_t count, uint64_t max, unsigned char rgba[4]);

/* Colors `counts` with render_color and encodes them as an RGBA PNG. Returns 0 with *png (to free) and
 * *size, or -1 if out of memory. */
int render_png(const uint64_t counts[RENDER_PIXELS], uint64_t max, unsigned char **png, size_t *size);

/* render_count then render_png with the header's densest pixel at `zoom`. *points = the points in the
 * tile. Returns 0, or -1 if the tile doesn't exist (zoom > GEO_MAX_ZOOM, x or y ≥ 2^zoom) or out of memory. */
int render_tile(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y, unsigned char **png, size_t *size,
                uint64_t *points);

#endif
