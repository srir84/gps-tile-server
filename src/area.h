/* area.h: exact point counts in a box, and the points themselves for export (DESIGN §5.6, §9.2 box rule).
 * The box is covered with Z-order squares: a square fully inside adds its slice length (2 binary
 * searches), a square on the edge is split in 4 until its slice is small, then checked point by point. */
#ifndef AREA_H
#define AREA_H

#include <stdint.h>

#include "tilefile.h"

/* A box in world units, edges included: a point (x, y) is inside if x0 ≤ x ≤ x1 and y0 ≤ y ≤ y1. The
 * degrees it was given in (bbox), for an export to keep its rows inside them. */
struct area_box {
    uint32_t x0, y0, x1, y1;
    double west, south, east, north;
};

/* Turns bbox=w,s,e,n text into a box (DESIGN §9.2): four plain decimal numbers, each in the valid input
 * range (§9.4), w ≤ e and s ≤ n. Returns 0, or -1 with *why saying what is wrong. */
int area_parse_bbox(const char *text, struct area_box *box, const char **why);

/* The number of points inside the box. */
uint64_t area_count(const struct tilefile *tf, const struct area_box *box);

/* Calls `emit` for the points inside the box in file order (sorted by code), at most `limit` of them,
 * until `emit` returns non-zero. Returns the points emitted. */
uint64_t area_points(const struct tilefile *tf, const struct area_box *box, uint64_t limit,
                     int (*emit)(uint32_t x, uint32_t y, void *context), void *context);

#endif
