/* gpstiles: command-line entry point. Commands are added step by step (DESIGN §9.1).
 * Exit codes: 0 = ok, 2 = usage error (unknown command, bad arguments). Errors are one line on stderr. */
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "geo.h"

/* Copies at most size-1 bytes of an untrusted argument, replacing control characters with '?',
 * so echoing it can't split the error over several lines or send terminal escape codes. */
static void printable_copy(char *out, size_t size, const char *in)
{
    size_t n = 0;
    for (; n + 1 < size && in[n] != '\0'; n++) {
        unsigned char c = (unsigned char)in[n];
        out[n] = (c < 0x20 || c == 0x7f) ? '?' : (char)c;
    }
    out[n] = '\0';
}

static void print_usage(void)
{
    fputs("usage: gpstiles <command> [arguments]\n"
          "\n"
          "commands:\n"
          "  help                     show this message\n"
          "  where LON LAT --zoom Z   print the map tile zoom/x/y for a place\n",
          stdout);
}

/* Parses a plain decimal number (sign, digits, point, exponent). Rejects everything else, so
 * "nan", "inf", hex, spaces and trailing junk never become a coordinate. Returns 0 if ok. */
static int parse_decimal(const char *text, double *out)
{
    if (text[0] == '\0' || strspn(text, "0123456789+-.eE") != strlen(text))
        return -1;
    char *end;
    double value = strtod(text, &end);
    if (end == text || *end != '\0' || !isfinite(value))
        return -1;
    *out = value;
    return 0;
}

/* Parses a zoom level: 1 or 2 digits, 0..GEO_MAX_ZOOM. Returns 0 if ok. */
static int parse_zoom(const char *text, unsigned *out)
{
    size_t length = strlen(text);
    if (length == 0 || length > 2 || strspn(text, "0123456789") != length)
        return -1;
    unsigned value = 0;
    for (size_t i = 0; i < length; i++)
        value = value * 10 + (unsigned)(text[i] - '0');
    if (value > GEO_MAX_ZOOM)
        return -1;
    *out = value;
    return 0;
}

static int where_error(const char *what, const char *arg, const char *want)
{
    char shown[33];
    printable_copy(shown, sizeof shown, arg);
    fprintf(stderr, "gpstiles where: bad %s '%s' (%s)\n", what, shown, want);
    return 2;
}

#define WHERE_USAGE "usage: gpstiles where LON LAT --zoom Z"

/* gpstiles where LON LAT --zoom Z: prints the tile zoom/x/y containing the place (DESIGN §9.1). */
static int cmd_where(int argc, char **argv)
{
    const char *place[2];
    int places = 0;
    const char *zoom_text = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--zoom") == 0 && zoom_text == NULL && i + 1 < argc) {
            zoom_text = argv[++i];
        } else if (places < 2 && strncmp(argv[i], "--", 2) != 0) {
            place[places++] = argv[i];
        } else {
            return where_error("argument", argv[i], WHERE_USAGE);
        }
    }
    if (places < 2 || zoom_text == NULL) {
        fputs("gpstiles where: missing arguments (" WHERE_USAGE ")\n", stderr);
        return 2;
    }

    double lon, lat;
    unsigned zoom;
    if (parse_decimal(place[0], &lon) != 0 || !geo_valid_lon(lon))
        return where_error("longitude", place[0], "want a number from -180 to 180");
    if (parse_decimal(place[1], &lat) != 0 || !geo_valid_lat(lat))
        return where_error("latitude", place[1], "want a number from -85.05112877980659 to 85.05112877980659");
    if (parse_zoom(zoom_text, &zoom) != 0)
        return where_error("zoom", zoom_text, "want a whole number from 0 to 24");

    struct geo_tile tile = geo_tile_of(geo_code(geo_world_x(lon), geo_world_y(lat)), zoom);
    printf("%u/%" PRIu32 "/%" PRIu32 "\n", tile.zoom, tile.x, tile.y);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fputs("gpstiles: missing command (try 'gpstiles help')\n", stderr);
        return 2;
    }
    if (strcmp(argv[1], "help") == 0 || strcmp(argv[1], "--help") == 0) {
        print_usage();
        return 0;
    }
    if (strcmp(argv[1], "where") == 0)
        return cmd_where(argc - 1, argv + 1);
    char name[65];
    printable_copy(name, sizeof name, argv[1]);
    fprintf(stderr, "gpstiles: unknown command '%s' (try 'gpstiles help')\n", name);
    return 2;
}
