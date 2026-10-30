/* gpstiles: command-line entry point. Commands are added step by step (DESIGN §9.1).
 * Exit codes: 0 = ok, 1 = a file can't be read or written, 2 = usage error (unknown command,
 * bad arguments). Errors are one line on stderr. */
#define _POSIX_C_SOURCE 200809L /* stat, mkstemp, fdopen with -std=c11 */

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "geo.h"
#include "import.h"

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
          "  where LON LAT --zoom Z   print the map tile zoom/x/y for a place\n"
          "  import --lon-col C --lat-col C [--delim D] [--skip N] -o OUT.pts FILE...\n"
          "                           read text rows into a .pts file and print what was kept and skipped\n",
          stdout);
}

/* Parses a whole number from 0 to max (digits only, at most 9 of them). Returns 0 if ok. */
static int parse_whole(const char *text, unsigned long max, unsigned long *out)
{
    size_t length = strlen(text);
    if (length == 0 || length > 9 || strspn(text, "0123456789") != length)
        return -1;
    unsigned long value = 0;
    for (size_t i = 0; i < length; i++)
        value = value * 10 + (unsigned long)(text[i] - '0');
    if (value > max)
        return -1;
    *out = value;
    return 0;
}

/* Prints "gpstiles COMMAND: bad WHAT 'ARG' (WANT)" with ARG made safe to show. Returns 2. */
static int bad_argument(const char *command, const char *what, const char *arg, const char *want)
{
    char shown[33];
    printable_copy(shown, sizeof shown, arg);
    fprintf(stderr, "gpstiles %s: bad %s '%s' (%s)\n", command, what, shown, want);
    return 2;
}

static int where_error(const char *what, const char *arg, const char *want)
{
    return bad_argument("where", what, arg, want);
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
    unsigned long zoom;
    if (import_parse_number(place[0], strlen(place[0]), &lon) != 0 || !geo_valid_lon(lon))
        return where_error("longitude", place[0], "want a number from -180 to 180");
    if (import_parse_number(place[1], strlen(place[1]), &lat) != 0 || !geo_valid_lat(lat))
        return where_error("latitude", place[1], "want a number from -85.05112877980659 to 85.05112877980659");
    if (parse_whole(zoom_text, GEO_MAX_ZOOM, &zoom) != 0)
        return where_error("zoom", zoom_text, "want a whole number from 0 to 24");

    struct geo_tile tile = geo_tile_of(geo_code(geo_world_x(lon), geo_world_y(lat)), (unsigned)zoom);
    printf("%u/%" PRIu32 "/%" PRIu32 "\n", tile.zoom, tile.x, tile.y);
    return 0;
}

#define IMPORT_USAGE "usage: gpstiles import --lon-col C --lat-col C [--delim D] [--skip N] -o OUT.pts FILE..."
#define MAX_COLUMN 10000

static int import_error(const char *what, const char *arg, const char *want)
{
    return bad_argument("import", what, arg, want);
}

/* Prints "gpstiles import: PATH: reason" for a file that can't be read or written. Returns 1. */
static int file_error(const char *path, int error)
{
    char shown[257];
    printable_copy(shown, sizeof shown, path);
    fprintf(stderr, "gpstiles import: %s: %s\n", shown, strerror(error));
    return 1;
}

static int parse_column(const char *option, const char *text, unsigned *out)
{
    unsigned long value;
    if (parse_whole(text, MAX_COLUMN, &value) != 0 || value == 0)
        return import_error(option, text, "want a column number from 1 to 10000");
    *out = (unsigned)value;
    return 0;
}

/* 1 if both paths name the same existing file, so writing one would wipe out the other. */
static int same_file(const char *a, const char *b)
{
    struct stat sa, sb;
    return stat(a, &sa) == 0 && stat(b, &sb) == 0 && sa.st_dev == sb.st_dev && sa.st_ino == sb.st_ino;
}

/* Imports every file into `out`. Returns 0, or 1 after printing which file failed. */
static int import_files(char **files, int count, const char *out_path, FILE *out,
                        const struct import_options *options, struct import_counts *counts)
{
    for (int i = 0; i < count; i++) {
        FILE *in = fopen(files[i], "rb");
        if (in == NULL)
            return file_error(files[i], errno);
        errno = 0;
        int status = import_stream(in, out, options, counts);
        int error = errno != 0 ? errno : EIO;
        int read_failed = ferror(in);
        fclose(in);
        if (status != 0)
            return file_error(read_failed ? files[i] : out_path, error);
    }
    return 0;
}

/* Opens a new temp file next to `path` (PATH.tmp-XXXXXX) with the permissions of the file it will
 * replace, or the usual ones for a new file. Returns the stream and sets *tmp_path (to free), or
 * returns NULL after printing why. */
static FILE *open_temp_beside(const char *path, char **tmp_path)
{
    static const char suffix[] = ".tmp-XXXXXX";
    size_t length = strlen(path);
    *tmp_path = malloc(length + sizeof suffix);
    if (*tmp_path == NULL) {
        file_error(path, ENOMEM);
        return NULL;
    }
    memcpy(*tmp_path, path, length);
    memcpy(*tmp_path + length, suffix, sizeof suffix);
    int fd = mkstemp(*tmp_path);
    FILE *f = NULL;
    if (fd >= 0) {
        mode_t mask = umask(0);
        umask(mask);
        struct stat old;
        mode_t mode = stat(path, &old) == 0 ? old.st_mode & 07777 : 0666 & ~mask; /* never widen access */
        if (fchmod(fd, mode) == 0) /* mkstemp makes it 0600 */
            f = fdopen(fd, "wb");
    }
    if (f == NULL) {
        int error = errno;
        if (fd >= 0) {
            close(fd);
            remove(*tmp_path);
        }
        free(*tmp_path);
        file_error(path, error);
    }
    return f;
}

/* gpstiles import ...: text rows → .pts, then one line of counts (DESIGN §8, §9.1). The .pts is
 * written to a temp file and renamed into place only on success, so a failed import never
 * changes an existing output file. */
static int cmd_import(int argc, char **argv)
{
    struct import_options options = {0, 0, ',', 0};
    const char *out_path = NULL;
    int i = 1;
    for (; i < argc && argv[i][0] == '-'; i++) {
        const char *option = argv[i];
        if (i + 1 >= argc)
            return import_error("argument", option, IMPORT_USAGE);
        const char *value = argv[++i];
        if (strcmp(option, "--lon-col") == 0) {
            if (parse_column(option, value, &options.lon_col) != 0)
                return 2;
        } else if (strcmp(option, "--lat-col") == 0) {
            if (parse_column(option, value, &options.lat_col) != 0)
                return 2;
        } else if (strcmp(option, "--delim") == 0) {
            options.delim = strcmp(value, "tab") == 0 ? '\t' : value[0];
            if ((strlen(value) != 1 && strcmp(value, "tab") != 0) || !import_delim_ok(options.delim))
                return import_error("--delim", value, "want one character that can't be in a number, or 'tab'");
        } else if (strcmp(option, "--skip") == 0) {
            if (parse_whole(value, 999999999, &options.skip) != 0)
                return import_error("--skip", value, "want a whole number of header lines");
        } else if (strcmp(option, "-o") == 0) {
            out_path = value;
        } else {
            return import_error("argument", option, IMPORT_USAGE);
        }
    }
    char **files = argv + i; /* everything after the options */
    int file_count = argc - i;
    if (options.lon_col == 0 || options.lat_col == 0 || out_path == NULL || file_count == 0) {
        fputs("gpstiles import: missing arguments (" IMPORT_USAGE ")\n", stderr);
        return 2;
    }
    if (options.lon_col == options.lat_col) {
        fputs("gpstiles import: --lon-col and --lat-col are the same column\n", stderr);
        return 2;
    }
    for (int f = 0; f < file_count; f++) {
        if (same_file(files[f], out_path))
            return import_error("-o", out_path, "it is also an input file");
    }

    char *tmp_path;
    FILE *out = open_temp_beside(out_path, &tmp_path);
    if (out == NULL)
        return 1;
    struct import_counts counts = {0, 0, 0, 0, 0};
    int status = import_files(files, file_count, out_path, out, &options, &counts);
    errno = 0;
    if (fclose(out) != 0 && status == 0)
        status = file_error(out_path, errno != 0 ? errno : EIO);
    if (status == 0 && rename(tmp_path, out_path) != 0)
        status = file_error(out_path, errno);
    if (status != 0)
        remove(tmp_path); /* never leave a half-written .pts behind */
    free(tmp_path);
    if (status != 0)
        return status;
    printf("rows=%" PRIu64 " imported=%" PRIu64 " skipped_zero=%" PRIu64 " skipped_out_of_range=%" PRIu64
           " skipped_malformed=%" PRIu64 "\n",
           counts.rows, counts.imported, counts.skipped_zero, counts.skipped_out_of_range, counts.skipped_malformed);
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
    if (strcmp(argv[1], "import") == 0)
        return cmd_import(argc - 1, argv + 1);
    char name[65];
    printable_copy(name, sizeof name, argv[1]);
    fprintf(stderr, "gpstiles: unknown command '%s' (try 'gpstiles help')\n", name);
    return 2;
}
