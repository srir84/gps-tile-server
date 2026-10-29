/* Unit and random tests for src/geo.c (TESTING.md §9, step 1). Known tiles come from the
 * OpenStreetMap formula (DESIGN §13); random tests check rules that must always hold. */
#include "suites.h"

#include <math.h>

#include "geo.h"

#define RANDOM_RUNS 100000
#define WORLD_UNIT_DEG (360.0 / 4294967296.0) /* one world unit in degrees of longitude */

static struct geo_tile tile_at(double lon, double lat, unsigned zoom)
{
    return geo_tile_of(geo_code(geo_world_x(lon), geo_world_y(lat)), zoom);
}

static double random_between(double low, double high)
{
    return low + (high - low) * ((double)(check_rand() >> 11) * 0x1p-53);
}

/* The slow way: bit by bit, as DESIGN §9.4 words it. */
static uint64_t slow_code(uint32_t x, uint32_t y)
{
    uint64_t code = 0;
    for (unsigned i = 0; i < 32; i++) {
        code |= (uint64_t)((x >> i) & 1u) << (2 * i);
        code |= (uint64_t)((y >> i) & 1u) << (2 * i + 1);
    }
    return code;
}

static void known_places_land_in_known_tiles(void)
{
    struct geo_tile beijing = tile_at(116.391, 39.907, 10);
    CHECK_EQ_U64(10, beijing.zoom);
    CHECK_EQ_U64(843, beijing.x);
    CHECK_EQ_U64(388, beijing.y);

    struct geo_tile new_york = tile_at(-74.006, 40.7128, 12);
    CHECK_EQ_U64(1205, new_york.x);
    CHECK_EQ_U64(1540, new_york.y);
}

static void edges_of_the_world(void)
{
    CHECK_EQ_U64(0, geo_world_x(-180.0));
    CHECK_EQ_U64(0, geo_world_x(180.0));
    CHECK_EQ_U64(UINT32_MAX, geo_world_x(180.0 - WORLD_UNIT_DEG));
    CHECK_EQ_U64(UINT32_MAX, geo_world_x(nextafter(180.0, 0.0))); /* lon + 180 rounds to 360 here */
    CHECK_EQ_U64(UINT32_C(1) << 31, geo_world_x(0.0));
    CHECK_EQ_U64(0, geo_world_y(GEO_MAX_LAT));
    CHECK_EQ_U64(UINT32_MAX, geo_world_y(-GEO_MAX_LAT));
    CHECK_EQ_U64(UINT32_C(1) << 31, geo_world_y(0.0));
}

static void valid_range_includes_both_ends_and_nothing_past(void)
{
    CHECK(geo_valid_lat(GEO_MAX_LAT) && geo_valid_lat(-GEO_MAX_LAT));
    CHECK(!geo_valid_lat(nextafter(GEO_MAX_LAT, INFINITY)));
    CHECK(!geo_valid_lat(nextafter(-GEO_MAX_LAT, -INFINITY)));
    CHECK(geo_valid_lon(180.0) && geo_valid_lon(-180.0));
    CHECK(!geo_valid_lon(nextafter(180.0, INFINITY)));
    CHECK(!geo_valid_lon(nextafter(-180.0, -INFINITY)));
    CHECK(!geo_valid_lon(NAN) && !geo_valid_lat(NAN));
    CHECK(!geo_valid_lon(INFINITY) && !geo_valid_lat(-INFINITY));
}

static void code_puts_x_in_even_bits_and_y_in_odd_bits(void)
{
    CHECK_EQ_U64(1, geo_code(1, 0));
    CHECK_EQ_U64(2, geo_code(0, 1));
    CHECK_EQ_U64(0x5555555555555555u, geo_code(UINT32_MAX, 0));
    CHECK_EQ_U64(0xAAAAAAAAAAAAAAAAu, geo_code(0, UINT32_MAX));
    for (int i = 0; i < RANDOM_RUNS; i++) {
        uint32_t x = (uint32_t)check_rand(), y = (uint32_t)check_rand();
        CHECK_EQ_U64(slow_code(x, y), geo_code(x, y));
    }
}

static void split_undoes_code(void)
{
    for (int i = 0; i < RANDOM_RUNS; i++) {
        uint64_t code = check_rand();
        uint32_t x, y;
        geo_split(code, &x, &y);
        CHECK_EQ_U64(code, geo_code(x, y));
    }
}

static void tile_of_code_matches_world_position_at_every_zoom(void)
{
    struct geo_tile whole = geo_tile_of(UINT64_MAX, 0);
    CHECK_EQ_U64(0, whole.x);
    CHECK_EQ_U64(0, whole.y);
    for (int i = 0; i < RANDOM_RUNS / 10; i++) {
        uint32_t x = (uint32_t)check_rand(), y = (uint32_t)check_rand();
        for (unsigned zoom = 1; zoom <= GEO_MAX_ZOOM; zoom++) {
            struct geo_tile tile = geo_tile_of(geo_code(x, y), zoom);
            CHECK_EQ_U64(zoom, tile.zoom);
            CHECK_EQ_U64(x >> (32 - zoom), tile.x);
            CHECK_EQ_U64(y >> (32 - zoom), tile.y);
        }
    }
}

static void random_place_round_trips_within_one_world_unit(void)
{
    for (int i = 0; i < RANDOM_RUNS; i++) {
        double lon = random_between(-180.0, 180.0);
        double lat = random_between(-GEO_MAX_LAT, GEO_MAX_LAT);
        uint32_t x, y;
        geo_split(geo_code(geo_world_x(lon), geo_world_y(lat)), &x, &y);

        double lon_error = fabs(geo_lon(x) - lon);
        lon_error = fmin(lon_error, 360.0 - lon_error); /* 180 and -180 are the same line */
        CHECK(lon_error <= WORLD_UNIT_DEG);
        /* Web Mercator stretches north-south by 1/cos(lat), so a unit is cos(lat) as many degrees. */
        double lat_unit_deg = WORLD_UNIT_DEG * cos(lat * (3.14159265358979323846 / 180.0));
        CHECK(fabs(geo_lat(y) - lat) <= lat_unit_deg * 1.000001);
    }
}

const struct check_case geo_cases[] = {
    {"known_places_land_in_known_tiles", "y axis flipped (north/south swapped), x and y swapped, or the wrong scale",
     known_places_land_in_known_tiles},
    {"edges_of_the_world",
     "lon 180 not wrapped to x = 0, a lon just below 180 wrapped too, or the south edge overflowing 32 bits",
     edges_of_the_world},
    {"valid_range_includes_both_ends_and_nothing_past",
     "< instead of <= drops the map's edge, a wider range lets impossible places in, or NaN slips through",
     valid_range_includes_both_ends_and_nothing_past},
    {"code_puts_x_in_even_bits_and_y_in_odd_bits", "x and y swapped in the code, or a wrong mask loses bits",
     code_puts_x_in_even_bits_and_y_in_odd_bits},
    {"split_undoes_code", "geo_split doesn't undo geo_code, so points come back in the wrong place",
     split_undoes_code},
    {"tile_of_code_matches_world_position_at_every_zoom",
     "the code's top bits don't give the tile (off-by-one shift, or a shift by 64 at zoom 0)",
     tile_of_code_matches_world_position_at_every_zoom},
    {"random_place_round_trips_within_one_world_unit",
     "the inverse (geo_lon/geo_lat) is off, so bounds and exports show the wrong places",
     random_place_round_trips_within_one_world_unit},
};
const size_t geo_cases_count = sizeof geo_cases / sizeof geo_cases[0];
