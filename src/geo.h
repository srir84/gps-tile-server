/* geo.h: map math (DESIGN §9.4). A place (longitude, latitude in degrees) → world x/y on the
 * Web Mercator square (32 bits each, 0,0 = north-west corner) → one 64-bit Z-order code → tile.
 * Pure functions: no files, no allocation. */
#ifndef GEO_H
#define GEO_H

#include <stdint.h>

#define GEO_MAX_LAT 85.05112877980659 /* Web Mercator's edge: the map is square up to here */
#define GEO_MAX_ZOOM 24

/* 1 if the value is in the valid input range (both ends included), else 0. NaN is invalid. */
int geo_valid_lon(double lon); /* -180 ≤ lon ≤ 180 */
int geo_valid_lat(double lat); /* -GEO_MAX_LAT ≤ lat ≤ GEO_MAX_LAT */

/* World position of a valid place; call geo_valid_* first. lon 180 wraps to x = 0 (the same
 * line as -180), and any lon below 180 stays in the last column. y = 0 is the north edge, and
 * the south edge is clamped to UINT32_MAX. */
uint32_t geo_world_x(double lon);
uint32_t geo_world_y(double lat);

/* Degrees at the north-west corner of world unit x or y: the inverse of the two above,
 * to within 1 world unit (≈ 0.93 cm at the equator). */
double geo_lon(uint32_t x);
double geo_lat(uint32_t y);

/* Z-order code: x in the even bits, y in the odd bits. geo_split undoes geo_code. */
uint64_t geo_code(uint32_t x, uint32_t y);
void geo_split(uint64_t code, uint32_t *x, uint32_t *y);

struct geo_tile {
    unsigned zoom;
    uint32_t x, y; /* 0 .. 2^zoom - 1, OpenStreetMap numbering */
};

/* The tile containing a code at zoom 0..GEO_MAX_ZOOM: the code's top 2*zoom bits. */
struct geo_tile geo_tile_of(uint64_t code, unsigned zoom);

#endif
