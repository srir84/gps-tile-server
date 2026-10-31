/* area.c: box counts and box points, declared in area.h (DESIGN §5.6). */
#include "area.h"

#include <string.h>

#include "geo.h"
#include "import.h"

#define SCAN_LIMIT 64 /* an edge square with at most this many points is checked point by point */

int area_parse_bbox(const char *text, struct area_box *box, const char **why)
{
    double v[4];
    const char *p = text;
    for (int k = 0; k < 4; k++) {
        size_t length = strcspn(p, ",");
        char number[64];
        if (length == 0 || length >= sizeof number || (k < 3) != (p[length] == ',')) {
            *why = "bbox must be four numbers: west,south,east,north";
            return -1;
        }
        memcpy(number, p, length);
        number[length] = '\0';
        if (import_parse_number(number, length, &v[k]) != 0) {
            *why = "bbox must be four plain decimal numbers: west,south,east,north";
            return -1;
        }
        p += length + 1;
    }
    double west = v[0], south = v[1], east = v[2], north = v[3];
    if (!geo_valid_lon(west) || !geo_valid_lon(east) || !geo_valid_lat(south) || !geo_valid_lat(north)) {
        *why = "bbox outside the map: longitude -180 to 180, latitude -85.05112877980659 to 85.05112877980659";
        return -1;
    }
    if (west > east || south > north) {
        *why = "bbox must have west <= east and south <= north (no boxes across the 180 line)";
        return -1;
    }
    /* Longitude 180 is stored as x = 0 (DESIGN §9.4), but as a box edge it means the world's east edge. */
    box->x0 = west == 180.0 ? UINT32_MAX : geo_world_x(west);
    box->x1 = east == 180.0 ? UINT32_MAX : geo_world_x(east);
    box->y0 = geo_world_y(north); /* y grows to the south */
    box->y1 = geo_world_y(south);
    return 0;
}

struct walk {
    const struct tilefile *tf;
    const struct area_box *box;
    uint64_t found, limit;
    int (*emit)(uint32_t x, uint32_t y, void *context); /* NULL: only count */
    void *context;
    int stopped;
};

/* Visits the square at `level` (0: the whole world, 32: one world unit) whose north-west corner is
 * (sx, sy), in Z order, so points are found in file order. */
static void walk(struct walk *w, unsigned level, uint32_t sx, uint32_t sy)
{
    const struct area_box *b = w->box;
    uint32_t span = (uint32_t)((UINT64_C(1) << (32 - level)) - 1); /* the square's last unit, from its corner */
    uint32_t ex = sx + span, ey = sy + span;
    if (w->stopped || ex < b->x0 || sx > b->x1 || ey < b->y0 || sy > b->y1)
        return; /* nothing more wanted, or no overlap */
    uint64_t low = geo_code(sx, sy), first, end;
    tilefile_range(w->tf, low, level == 32 ? low : low | (UINT64_MAX >> (2 * level)), &first, &end);
    int inside = sx >= b->x0 && ex <= b->x1 && sy >= b->y0 && ey <= b->y1;
    if (first == end)
        return;
    if (inside && w->emit == NULL) {
        w->found += end - first;
        return;
    }
    if (!inside && end - first > SCAN_LIMIT) { /* level < 32: a one-unit square is never partly inside */
        uint32_t half = (uint32_t)1 << (31 - level);
        walk(w, level + 1, sx, sy); /* children in code order: x is the low bit of each pair */
        walk(w, level + 1, sx + half, sy);
        walk(w, level + 1, sx, sy + half);
        walk(w, level + 1, sx + half, sy + half);
        return;
    }
    for (uint64_t i = first; i < end; i++) {
        uint32_t x, y;
        geo_split(tilefile_code(w->tf, i), &x, &y);
        if (!inside && (x < b->x0 || x > b->x1 || y < b->y0 || y > b->y1))
            continue;
        if (w->emit != NULL && (w->found == w->limit || w->emit(x, y, w->context) != 0)) {
            w->stopped = 1;
            return;
        }
        w->found++;
    }
}

uint64_t area_count(const struct tilefile *tf, const struct area_box *box)
{
    struct walk w = {tf, box, 0, 0, NULL, NULL, 0};
    walk(&w, 0, 0, 0);
    return w.found;
}

uint64_t area_points(const struct tilefile *tf, const struct area_box *box, uint64_t limit,
                     int (*emit)(uint32_t x, uint32_t y, void *context), void *context)
{
    struct walk w = {tf, box, 0, limit, emit, context, 0};
    walk(&w, 0, 0, 0);
    return w.found;
}
