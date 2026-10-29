/* geo.c: map math declared in geo.h (DESIGN §9.4). */
#include "geo.h"

#include <math.h>

#define PI 3.14159265358979323846 /* M_PI isn't part of C11 */
#define WORLD 4294967296.0        /* 2^32 world units per side */

int geo_valid_lon(double lon)
{
    return lon >= -180.0 && lon <= 180.0; /* false for NaN */
}

int geo_valid_lat(double lat)
{
    return lat >= -GEO_MAX_LAT && lat <= GEO_MAX_LAT;
}

uint32_t geo_world_x(double lon)
{
    if (lon == 180.0) /* the same line as -180 */
        return 0;
    double units = floor((lon + 180.0) / 360.0 * WORLD);
    if (units > (double)UINT32_MAX) /* lon just below 180: lon + 180 can round up to 360 */
        return UINT32_MAX;
    return (uint32_t)units;
}

uint32_t geo_world_y(double lat)
{
    /* Same expression as the OpenStreetMap tile formula, so tiles match it exactly. */
    double units = floor((1.0 - asinh(tan(lat * (PI / 180.0))) / PI) / 2.0 * WORLD);
    if (units < 0.0) /* rounding at the north edge */
        return 0;
    if (units > (double)UINT32_MAX) /* the south edge itself is 2^32 */
        return UINT32_MAX;
    return (uint32_t)units;
}

double geo_lon(uint32_t x)
{
    return x / WORLD * 360.0 - 180.0;
}

double geo_lat(uint32_t y)
{
    return atan(sinh(PI * (1.0 - 2.0 * (y / WORLD)))) * (180.0 / PI);
}

/* Moves bit i of v to bit 2i. */
static uint64_t spread(uint32_t v)
{
    uint64_t b = v;
    b = (b | (b << 16)) & 0x0000FFFF0000FFFFu;
    b = (b | (b << 8)) & 0x00FF00FF00FF00FFu;
    b = (b | (b << 4)) & 0x0F0F0F0F0F0F0F0Fu;
    b = (b | (b << 2)) & 0x3333333333333333u;
    b = (b | (b << 1)) & 0x5555555555555555u;
    return b;
}

/* Moves bit 2i of b to bit i, dropping the odd bits. */
static uint32_t squeeze(uint64_t b)
{
    b &= 0x5555555555555555u;
    b = (b | (b >> 1)) & 0x3333333333333333u;
    b = (b | (b >> 2)) & 0x0F0F0F0F0F0F0F0Fu;
    b = (b | (b >> 4)) & 0x00FF00FF00FF00FFu;
    b = (b | (b >> 8)) & 0x0000FFFF0000FFFFu;
    b = (b | (b >> 16)) & 0x00000000FFFFFFFFu;
    return (uint32_t)b;
}

uint64_t geo_code(uint32_t x, uint32_t y)
{
    return spread(x) | (spread(y) << 1);
}

void geo_split(uint64_t code, uint32_t *x, uint32_t *y)
{
    *x = squeeze(code);
    *y = squeeze(code >> 1);
}

struct geo_tile geo_tile_of(uint64_t code, unsigned zoom)
{
    struct geo_tile tile = {zoom, 0, 0};
    if (zoom > 0) /* a shift by 64 is undefined */
        geo_split(code >> (64 - 2 * zoom), &tile.x, &tile.y);
    return tile;
}
