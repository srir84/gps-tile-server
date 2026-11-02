/* gpstiles: command-line entry point. Commands are added step by step (DESIGN §9.1).
 * Exit codes: 0 = ok, 1 = a file can't be read or written, 2 = usage error (unknown command,
 * bad arguments). Errors are one line on stderr. */
#define _POSIX_C_SOURCE 200809L /* stat, mkstemp, fdopen with -std=c11 */

#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "build.h"
#include "geo.h"
#include "import.h"
#include "render.h"
#include "server.h"
#include "tilefile.h"

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
          "                           read text rows into a .pts file and print what was kept and skipped\n"
          "  build [--mem SIZE] [--tmp DIR] -o OUT.gpt IN.pts...\n"
          "                           sort the points into a .gpt tile file\n"
          "  info FILE.gpt            print the point count, file size, bounds and start view\n"
          "                           (west,south,east,north) and the densest pixel per zoom\n"
          "  count FILE.gpt Z X Y     print the number of points in map tile Z/X/Y\n"
          "  render FILE.gpt Z X Y -o OUT.png\n"
          "                           draw map tile Z/X/Y as a 256 x 256 heat-map PNG\n"
          "  bench FILE.gpt           time drawing tiles at each zoom: render only, no HTTP (p50/p99 in ms)\n"
          "  serve [--host 127.0.0.1] [--port 8080] [--timeout 10] FILE.gpt...\n"
          "                           serve the datasets' tiles and info over HTTP (--port 0: any free port)\n",
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

#define IMPORT_USAGE "usage: gpstiles import (--lon-col C --lat-col C | --polyline C | --gpx) [--delim D] [--skip N] -o OUT.pts FILE..."
#define MAX_COLUMN 10000

static int import_error(const char *what, const char *arg, const char *want)
{
    return bad_argument("import", what, arg, want);
}

/* Prints "gpstiles COMMAND: PATH: reason" for a file that can't be read or written, with the whole
 * path (control characters shown as '?'), so a file to delete by hand is always named in full. Returns 1. */
static int file_error(const char *command, const char *path, const char *reason)
{
    size_t length = strlen(path);
    char *shown = malloc(length + 1);
    if (shown != NULL)
        printable_copy(shown, length + 1, path);
    fprintf(stderr, "gpstiles %s: %s: %s\n", command, shown != NULL ? shown : "(out of memory)", reason);
    free(shown);
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
            return file_error("import", files[i], strerror(errno));
        errno = 0;
        int status = import_stream(in, out, options, counts);
        int error = errno != 0 ? errno : EIO;
        int read_failed = ferror(in);
        fclose(in);
        if (status != 0)
            return file_error("import", read_failed ? files[i] : out_path, strerror(error));
    }
    return 0;
}

/* The temp output being written, if any. If the program is killed (Ctrl-C, kill, closing the terminal)
 * the signal handler removes it, so a half-written file never stays behind to be mistaken for data. */
static const char *volatile temp_to_remove;

static void on_fatal_signal(int sig)
{
    const char *path = temp_to_remove;
    if (path != NULL)
        unlink(path);       /* unlink, signal and raise are safe to call in a signal handler */
    signal(sig, SIG_DFL);
    raise(sig);             /* delivered once this handler returns: die as the signal intended */
}

static const int fatal_signals[] = {SIGINT, SIGTERM, SIGHUP, SIGQUIT};

/* Installs on_fatal_signal once. A signal that was ignored when the program started stays ignored:
 * `nohup gpstiles build ...` must survive a closed terminal, as any program would. */
static void install_signal_handlers(void)
{
    static int installed;
    if (installed)
        return;
    struct sigaction action, old;
    memset(&action, 0, sizeof action);
    action.sa_handler = on_fatal_signal;
    sigemptyset(&action.sa_mask);
    for (size_t i = 0; i < sizeof fatal_signals / sizeof fatal_signals[0]; i++) {
        if (sigaction(fatal_signals[i], NULL, &old) == 0 && old.sa_handler != SIG_IGN)
            sigaction(fatal_signals[i], &action, NULL);
    }
    signal(SIGXFSZ, SIG_IGN); /* a file-size limit then fails the write (EFBIG): normal cleanup */
    installed = 1;
}

/* Blocks (or unblocks) the fatal signals, so none lands between creating a temp file and recording it. */
static void block_fatal_signals(int block)
{
    sigset_t set;
    sigemptyset(&set);
    for (size_t i = 0; i < sizeof fatal_signals / sizeof fatal_signals[0]; i++)
        sigaddset(&set, fatal_signals[i]);
    sigprocmask(block ? SIG_BLOCK : SIG_UNBLOCK, &set, NULL);
}

/* Opens a new temp file next to `path` (PATH.tmp-XXXXXX) with the permissions of the file it will
 * replace, or the usual ones for a new file. Returns the stream and sets *tmp_path (to free), or
 * returns NULL with *tmp_path NULL after printing why. */
static FILE *open_temp_beside(const char *command, const char *path, char **tmp_path)
{
    static const char suffix[] = ".tmp-XXXXXX";
    size_t length = strlen(path);
    *tmp_path = malloc(length + sizeof suffix);
    if (*tmp_path == NULL) {
        file_error(command, path, strerror(ENOMEM));
        return NULL;
    }
    memcpy(*tmp_path, path, length);
    memcpy(*tmp_path + length, suffix, sizeof suffix);
    install_signal_handlers();
    block_fatal_signals(1);
    int fd = mkstemp(*tmp_path);
    if (fd >= 0)
        temp_to_remove = *tmp_path;
    block_fatal_signals(0); /* a signal that came meanwhile is handled now, and removes the file */
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
        temp_to_remove = NULL;
        free(*tmp_path);
        *tmp_path = NULL;
        file_error(command, path, strerror(error));
    }
    return f;
}

/* Prints that a temp file couldn't be removed and must be deleted by hand. */
static void left_behind(const char *command, const char *path, int error)
{
    char reason[160];
    snprintf(reason, sizeof reason, "left behind, delete it by hand (%s)", strerror(error));
    file_error(command, path, reason);
}

/* Renames the temp output into place if status is 0, else removes it. Either way it is no longer a
 * temp file to remove on a signal. Returns the final status. */
static int finish_temp(const char *command, const char *tmp_path, const char *out_path, int status)
{
    if (status == 0 && rename(tmp_path, out_path) != 0)
        status = file_error(command, out_path, strerror(errno));
    if (status != 0 && remove(tmp_path) != 0) /* never leave a half-written file behind */
        left_behind(command, tmp_path, errno);
    temp_to_remove = NULL;
    return status;
}

/* gpstiles import ...: text rows → .pts, then one line of counts (DESIGN §8, §9.1). The .pts is
 * written to a temp file and renamed into place only on success, so a failed import never
 * changes an existing output file. */
static int cmd_import(int argc, char **argv)
{
    struct import_options options = {0, 0, ',', 0, 0, 0};
    const char *out_path = NULL;
    int i = 1, delim_given = 0, skip_given = 0;
    for (; i < argc && argv[i][0] == '-'; i++) {
        const char *option = argv[i];
        if (strcmp(option, "--gpx") == 0) { /* takes no value */
            options.gpx = 1;
            continue;
        }
        if (i + 1 >= argc)
            return import_error("argument", option, IMPORT_USAGE);
        const char *value = argv[++i];
        if (strcmp(option, "--lon-col") == 0) {
            if (parse_column(option, value, &options.lon_col) != 0)
                return 2;
        } else if (strcmp(option, "--lat-col") == 0) {
            if (parse_column(option, value, &options.lat_col) != 0)
                return 2;
        } else if (strcmp(option, "--polyline") == 0) {
            if (parse_column(option, value, &options.polyline_col) != 0)
                return 2;
        } else if (strcmp(option, "--delim") == 0) {
            delim_given = 1;
            options.delim = strcmp(value, "tab") == 0 ? '\t' : value[0];
            if ((strlen(value) != 1 && strcmp(value, "tab") != 0) || !import_delim_ok(options.delim))
                return import_error("--delim", value, "want one character that can't be in a number, or 'tab'");
        } else if (strcmp(option, "--skip") == 0) {
            skip_given = 1;
            if (parse_whole(value, 999999999, &options.skip) != 0)
                return import_error("--skip", value, "want a whole number of header lines");
        } else if (strcmp(option, "-o") == 0) {
            if (value[0] == '\0')
                return import_error("-o", value, "want a file name");
            out_path = value;
        } else {
            return import_error("argument", option, IMPORT_USAGE);
        }
    }
    char **files = argv + i; /* everything after the options */
    int file_count = argc - i;
    if (options.gpx && (options.lon_col != 0 || options.lat_col != 0 || options.polyline_col != 0 || delim_given || skip_given)) {
        fputs("gpstiles import: --gpx reads <trkpt> tags: not with column, --delim or --skip options\n", stderr);
        return 2;
    }
    if (options.polyline_col != 0 && (options.lon_col != 0 || options.lat_col != 0)) {
        fputs("gpstiles import: --polyline reads both places from one column: not with --lon-col or --lat-col\n", stderr);
        return 2;
    }
    if (options.polyline_col != 0 && strchr("\"[]", options.delim) != NULL)
        return import_error("--delim", options.delim == '"' ? "\"" : options.delim == '[' ? "[" : "]",
                            "with --polyline, want a character that isn't a quote or a bracket");
    if (((options.lon_col == 0 || options.lat_col == 0) && options.polyline_col == 0 && !options.gpx) || out_path == NULL ||
        file_count == 0) {
        fputs("gpstiles import: missing arguments (" IMPORT_USAGE ")\n", stderr);
        return 2;
    }
    if (options.polyline_col == 0 && !options.gpx && options.lon_col == options.lat_col) {
        fputs("gpstiles import: --lon-col and --lat-col are the same column\n", stderr);
        return 2;
    }
    for (int f = 0; f < file_count; f++) {
        if (same_file(files[f], out_path))
            return import_error("-o", out_path, "it is also an input file");
    }

    char *tmp_path;
    FILE *out = open_temp_beside("import", out_path, &tmp_path);
    if (out == NULL)
        return 1;
    struct import_counts counts = {0, 0, 0, 0, 0, 0};
    int status = import_files(files, file_count, out_path, out, &options, &counts);
    errno = 0;
    if (fclose(out) != 0 && status == 0)
        status = file_error("import", out_path, strerror(errno != 0 ? errno : EIO));
    status = finish_temp("import", tmp_path, out_path, status);
    free(tmp_path);
    if (status != 0)
        return status;
    if (options.polyline_col != 0) /* a row is a list of points: how many points the lists held */
        printf("rows=%" PRIu64 " points=%" PRIu64 " ", counts.rows, counts.points);
    else
        printf("rows=%" PRIu64 " ", counts.rows);
    printf("imported=%" PRIu64 " skipped_zero=%" PRIu64 " skipped_out_of_range=%" PRIu64 " skipped_malformed=%" PRIu64 "\n",
           counts.imported, counts.skipped_zero, counts.skipped_out_of_range, counts.skipped_malformed);
    return 0;
}

#define BUILD_USAGE "usage: gpstiles build [--mem SIZE] [--tmp DIR] -o OUT.gpt IN.pts..."
#define MIB (1024ull * 1024ull)

static int build_error(const char *what, const char *arg, const char *want)
{
    return bad_argument("build", what, arg, want);
}

/* Parses a size such as 512M or 1G (K, M, G: powers of 1024) from 1M to 64G. Returns 0 if ok. */
static int parse_mem(const char *text, uint64_t *bytes)
{
    size_t length = strlen(text);
    char digits[10];
    if (length < 2 || length - 1 >= sizeof digits)
        return -1;
    const char *units = "KkMmGg", *unit = strchr(units, text[length - 1]);
    if (unit == NULL)
        return -1;
    memcpy(digits, text, length - 1);
    digits[length - 1] = '\0';
    unsigned long count;
    if (parse_whole(digits, 999999999, &count) != 0)
        return -1;
    uint64_t value = (uint64_t)count << (10 * (1 + (unit - units) / 2)); /* at most ~2^60: no overflow */
    if (value < MIB || value > 64 * 1024 * MIB)
        return -1;
    *bytes = value;
    return 0;
}

/* The folder part of a path ("." if it has none), to free. NULL if out of memory. */
static char *folder_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    if (slash == NULL)
        return strdup(".");
    size_t length = slash == path ? 1 : (size_t)(slash - path);
    char *folder = malloc(length + 1);
    if (folder != NULL) {
        memcpy(folder, path, length);
        folder[length] = '\0';
    }
    return folder;
}

/* Opens an empty run file in `folder` and removes its name at once, so it is never left behind,
 * even if the program is killed. Returns NULL after printing why. If the name can't be removed,
 * nothing is written to it and the error names the file to delete by hand. */
static FILE *open_run_file(const char *folder)
{
    static const char name[] = "/gpstiles-runs-XXXXXX";
    size_t length = strlen(folder);
    char *path = malloc(length + sizeof name);
    if (path == NULL) {
        file_error("build", folder, strerror(ENOMEM));
        return NULL;
    }
    memcpy(path, folder, length);
    memcpy(path + length, name, sizeof name);
    FILE *f = NULL;
    int fd = mkstemp(path);
    int error = errno;
    if (fd >= 0 && unlink(path) != 0) {
        left_behind("build", path, errno);
        close(fd);
        free(path);
        return NULL;
    }
    if (fd >= 0) {
        f = fdopen(fd, "w+b");
        error = errno;
        if (f == NULL)
            close(fd);
    }
    if (f == NULL)
        file_error("build", folder, strerror(error));
    free(path);
    return f;
}

/* Prints why a build failed. `file` is the input being read, if any. Returns the exit code. */
static int build_failed(enum build_status status, int error, const char *file, const char *out_path,
                        const char *tmp_folder)
{
    const char *reason = strerror(error != 0 ? error : EIO);
    switch (status) {
    case BUILD_READ_ERROR:
        return file_error("build", file, reason);
    case BUILD_BAD_INPUT:
        return file_error("build", file, "not a .pts file (its size is not a multiple of 8 bytes)");
    case BUILD_GPT_INPUT:
        return file_error("build", file, "is a .gpt file (or a killed build's leftover), not a .pts (build reads the output of import)");
    case BUILD_TOO_MANY_RUNS:
        fputs("gpstiles build: --mem is too small for this input (more than 256 sorted runs); raise --mem\n",
              stderr);
        return 2;
    case BUILD_TEMP_ERROR:
        return file_error("build", tmp_folder, reason);
    case BUILD_WRITE_ERROR:
        return file_error("build", out_path, reason);
    case BUILD_NO_MEMORY:
    case BUILD_OK:
        break;
    }
    fputs("gpstiles build: out of memory (lower --mem)\n", stderr);
    return 1;
}

/* Checks what can be checked before any work, so a long sort never ends in an error that was there
 * from the start: -o isn't a folder, every input exists and isn't a folder, a regular input's size is
 * a multiple of 8, and --mem is big enough for the inputs in at most 256 runs. Pipes are checked as
 * they are read. Returns 0, or the exit code after printing why. */
static int check_build_files(char **files, int count, const char *out_path, uint64_t mem)
{
    struct stat st;
    if (stat(out_path, &st) == 0 && S_ISDIR(st.st_mode))
        return file_error("build", out_path, "is a folder (-o wants the .gpt file to write)");
    uint64_t total = 0;
    for (int f = 0; f < count; f++) {
        if (stat(files[f], &st) != 0)
            return file_error("build", files[f], strerror(errno));
        if (S_ISDIR(st.st_mode))
            return file_error("build", files[f], "is a folder, not a .pts file");
        if (!S_ISREG(st.st_mode))
            continue; /* a pipe can be read only once: build_add checks it */
        if (st.st_size % 8 != 0)
            return file_error("build", files[f], "not a .pts file (its size is not a multiple of 8 bytes)");
        FILE *in = fopen(files[f], "rb");
        unsigned char head[16];
        if (in == NULL)
            return file_error("build", files[f], strerror(errno));
        size_t got = fread(head, 1, sizeof head, in);
        fclose(in);
        if (got == sizeof head && build_is_gpt(head))
            return build_failed(BUILD_GPT_INPUT, 0, files[f], NULL, NULL);
        total += (uint64_t)st.st_size;
    }
    uint64_t chunk = mem / sizeof(uint64_t) * sizeof(uint64_t); /* bytes sorted per run */
    if ((total + chunk - 1) / chunk > BUILD_MAX_RUNS) {
        uint64_t least = (total + BUILD_MAX_RUNS * MIB - 1) / (BUILD_MAX_RUNS * MIB); /* in MiB */
        fprintf(stderr, "gpstiles build: --mem is too small for %" PRIu64 " bytes of input (more than 256 sorted runs); "
                        "use --mem %" PRIu64 "M or more\n", total, least);
        return 2;
    }
    return 0;
}

/* gpstiles build ...: .pts files → one sorted .gpt (DESIGN §5.3, §9.1). Like import, the output is
 * written to a temp file and renamed into place only on success. Prints the point and run counts. */
static int cmd_build(int argc, char **argv)
{
    uint64_t mem = 1024 * MIB;
    const char *tmp_folder = NULL, *out_path = NULL;
    int i = 1;
    for (; i < argc && argv[i][0] == '-'; i++) {
        const char *option = argv[i];
        if (i + 1 >= argc)
            return build_error("argument", option, BUILD_USAGE);
        const char *value = argv[++i];
        if (strcmp(option, "--mem") == 0) {
            if (parse_mem(value, &mem) != 0)
                return build_error("--mem", value, "want a size from 1M to 64G, like 512M or 1G");
        } else if (strcmp(option, "--tmp") == 0) {
            if (value[0] == '\0') /* "" + "/gpstiles-runs-..." would be the root folder */
                return build_error("--tmp", value, "want a folder");
            tmp_folder = value;
        } else if (strcmp(option, "-o") == 0) {
            if (value[0] == '\0')
                return build_error("-o", value, "want a file name");
            out_path = value;
        } else {
            return build_error("argument", option, BUILD_USAGE);
        }
    }
    char **files = argv + i;
    int file_count = argc - i;
    if (out_path == NULL || file_count == 0) {
        fputs("gpstiles build: missing arguments (" BUILD_USAGE ")\n", stderr);
        return 2;
    }
    for (int f = 0; f < file_count; f++) {
        if (files[f][0] == '-')
            return build_error("argument", files[f], "options go before the input files");
        if (same_file(files[f], out_path))
            return build_error("-o", out_path, "it is also an input file");
    }
    int status = check_build_files(files, file_count, out_path, mem);
    if (status != 0)
        return status;

    status = 1;
    char *default_tmp = NULL, *tmp_path = NULL;
    FILE *runs = NULL;
    struct build *b = NULL;
    struct build_header header;
    size_t runs_used = 0;
    FILE *out = open_temp_beside("build", out_path, &tmp_path);
    if (out == NULL)
        goto done;
    if (tmp_folder == NULL) {
        tmp_folder = default_tmp = folder_of(out_path);
        if (default_tmp == NULL) {
            status = build_failed(BUILD_NO_MEMORY, 0, NULL, out_path, NULL);
            goto done;
        }
    }
    runs = open_run_file(tmp_folder);
    if (runs == NULL)
        goto done;
    b = build_start((size_t)(mem / sizeof(uint64_t)), runs);
    if (b == NULL) {
        status = build_failed(BUILD_NO_MEMORY, 0, NULL, out_path, tmp_folder);
        goto done;
    }
    for (int f = 0; f < file_count; f++) {
        FILE *in = fopen(files[f], "rb");
        if (in == NULL) {
            status = file_error("build", files[f], strerror(errno));
            goto done;
        }
        errno = 0;
        enum build_status result = build_add(b, in);
        int error = errno;
        fclose(in);
        if (result != BUILD_OK) {
            status = build_failed(result, error, files[f], out_path, tmp_folder);
            goto done;
        }
    }
    errno = 0;
    enum build_status result = build_finish(b, out, &header, &runs_used);
    status = result == BUILD_OK ? 0 : build_failed(result, errno, NULL, out_path, tmp_folder);
done:
    build_free(b);
    if (runs != NULL)
        fclose(runs);
    if (out != NULL) {
        errno = 0;
        if (fclose(out) != 0 && status == 0)
            status = file_error("build", out_path, strerror(errno != 0 ? errno : EIO));
        status = finish_temp("build", tmp_path, out_path, status);
    }
    free(tmp_path);
    free(default_tmp);
    if (status == 0)
        printf("points=%" PRIu64 " runs=%zu\n", header.count, runs_used);
    return status;
}

/* Opens a .gpt for `command`. Returns 0, or 1 after printing why the file can't be used. */
static int open_gpt(const char *command, const char *path, struct tilefile *tf)
{
    switch (tilefile_open(path, tf)) {
    case TILEFILE_OK:
        return 0;
    case TILEFILE_OPEN_ERROR:
        return file_error(command, path, strerror(errno));
    case TILEFILE_NOT_REGULAR:
        return file_error(command, path, "not a regular file");
    case TILEFILE_NOT_GPT:
        return file_error(command, path, "not a .gpt file (it doesn't start with the GPSTILE label)");
    case TILEFILE_UNFINISHED:
        return file_error(command, path, "an unfinished .gpt (its build was stopped before the end): build it again");
    case TILEFILE_BAD_VERSION:
        return file_error(command, path, "a .gpt version this gpstiles can't read (it reads version 1)");
    case TILEFILE_BAD_HEADER:
        return file_error(command, path, "broken .gpt: the header size isn't 256");
    case TILEFILE_CUT_SHORT:
        return file_error(command, path, "broken .gpt: cut short inside the 256-byte header");
    case TILEFILE_SIZE_MISMATCH:
        return file_error(command, path, "broken .gpt: the file size doesn't match the header's point count");
    case TILEFILE_BAD_STATS:
        return file_error(command, path, "broken .gpt: impossible header stats (bounds, view box or densest pixels)");
    }
    return file_error(command, path, "can't be read");
}

/* The argument to blame in a usage error: the first one that looks like an option (a mistyped one,
 * wherever it was put), else the first extra one, argv[expected]. */
static const char *first_option(int argc, char **argv, int expected)
{
    for (int i = 1; i < argc; i++) {
        if (argv[i][0] == '-' && (i == 1 || (argv[i][1] != '\0' && (argv[i][1] < '0' || argv[i][1] > '9'))))
            return argv[i];
    }
    return argv[expected < argc ? expected : argc - 1];
}

#define INFO_USAGE "usage: gpstiles info FILE.gpt"

/* Prints NAME=west,south,east,north in degrees for a box in world units (y grows to the south). */
static void print_box(const char *name, uint64_t count, uint32_t min_x, uint32_t min_y, uint32_t max_x,
                      uint32_t max_y)
{
    if (count == 0)
        printf("%s=none\n", name);
    else
        printf("%s=%.6f,%.6f,%.6f,%.6f\n", name, geo_lon(min_x), geo_lat(max_y), geo_lon(max_x), geo_lat(min_y));
}

/* gpstiles info FILE.gpt: prints the header (DESIGN §9.1, §9.3), one key=value per line. */
static int cmd_info(int argc, char **argv)
{
    if (argc < 2) {
        fputs("gpstiles info: missing arguments (" INFO_USAGE ")\n", stderr);
        return 2;
    }
    if (argv[1][0] == '-' || argc > 2)
        return bad_argument("info", "argument", first_option(argc, argv, 2), INFO_USAGE);
    struct tilefile tf;
    if (open_gpt("info", argv[1], &tf) != 0)
        return 1;
    const struct build_header *h = &tf.header;
    printf("points=%" PRIu64 "\nbytes=%zu\n", h->count, tf.size);
    print_box("bounds", h->count, h->min_x, h->min_y, h->max_x, h->max_y);
    print_box("view", h->count, h->view_min_x, h->view_min_y, h->view_max_x, h->view_max_y);
    fputs("max_pixel=", stdout);
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        printf("%" PRIu64 "%s", h->max_pixel_count[z], z < GEO_MAX_ZOOM ? "," : "\n");
    tilefile_close(&tf);
    return 0;
}

/* Parses Z X Y for `command`: zoom 0..24, x and y below 2^zoom. Returns 0, or 2 after printing why. */
static int parse_tile(const char *command, char **text, unsigned *zoom, uint32_t *x, uint32_t *y)
{
    unsigned long z, tx, ty;
    if (parse_whole(text[0], GEO_MAX_ZOOM, &z) != 0)
        return bad_argument(command, "zoom", text[0], "want a whole number from 0 to 24");
    char want[64];
    snprintf(want, sizeof want, "want a whole number from 0 to %lu at zoom %lu", (1ul << z) - 1, z);
    if (parse_whole(text[1], (1ul << z) - 1, &tx) != 0)
        return bad_argument(command, "x", text[1], want);
    if (parse_whole(text[2], (1ul << z) - 1, &ty) != 0)
        return bad_argument(command, "y", text[2], want);
    *zoom = (unsigned)z;
    *x = (uint32_t)tx;
    *y = (uint32_t)ty;
    return 0;
}

#define COUNT_USAGE "usage: gpstiles count FILE.gpt Z X Y"

/* gpstiles count FILE.gpt Z X Y: prints the number of points in one tile (DESIGN §9.1). */
static int cmd_count(int argc, char **argv)
{
    if (argc < 5) {
        fputs("gpstiles count: missing arguments (" COUNT_USAGE ")\n", stderr);
        return 2;
    }
    if (argv[1][0] == '-' || argc > 5) /* no options yet: a dash is a typo, not a file name */
        return bad_argument("count", "argument", first_option(argc, argv, 5), COUNT_USAGE);
    unsigned zoom;
    uint32_t x, y;
    if (parse_tile("count", argv + 2, &zoom, &x, &y) != 0)
        return 2;
    struct tilefile tf;
    if (open_gpt("count", argv[1], &tf) != 0)
        return 1;
    uint64_t first, end;
    tilefile_tile(&tf, zoom, x, y, &first, &end);
    printf("points=%" PRIu64 "\n", end - first);
    tilefile_close(&tf);
    return 0;
}

#define RENDER_USAGE "usage: gpstiles render FILE.gpt Z X Y -o OUT.png"

/* gpstiles render FILE.gpt Z X Y -o OUT.png: draws one tile to a PNG file (DESIGN §5.5, §9.1), the same
 * picture the server sends. The PNG is written to a temp file and renamed into place. */
static int cmd_render(int argc, char **argv)
{
    const char *out_path = NULL;
    char *args[4];
    int n = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-o") == 0 && out_path == NULL) {
            if (i + 1 >= argc || argv[i + 1][0] == '\0')
                return bad_argument("render", "-o", i + 1 < argc ? argv[i + 1] : argv[i], RENDER_USAGE);
            out_path = argv[++i];
        } else if (n < 4 && (n > 0 || argv[i][0] != '-')) { /* a dash is a typo only in the file name */
            args[n++] = argv[i];
        } else {
            return bad_argument("render", "argument", argv[i], RENDER_USAGE);
        }
    }
    if (n < 4 || out_path == NULL) {
        fputs("gpstiles render: missing arguments (" RENDER_USAGE ")\n", stderr);
        return 2;
    }
    unsigned zoom;
    uint32_t x, y;
    if (parse_tile("render", args + 1, &zoom, &x, &y) != 0)
        return 2;
    if (same_file(args[0], out_path)) /* the rename would replace the dataset with a picture */
        return bad_argument("render", "-o", out_path, "it is also the input file");
    struct tilefile tf;
    if (open_gpt("render", args[0], &tf) != 0)
        return 1;
    unsigned char *png;
    size_t size;
    uint64_t points;
    int failed = render_tile(&tf, zoom, x, y, &png, &size, &points);
    tilefile_close(&tf);
    if (failed) {
        fputs("gpstiles render: out of memory\n", stderr);
        return 1;
    }
    char *tmp_path;
    FILE *out = open_temp_beside("render", out_path, &tmp_path);
    int status = 1;
    if (out != NULL) {
        errno = 0;
        int written = fwrite(png, 1, size, out) == size;
        status = fclose(out) == 0 && written ? 0 : file_error("render", out_path, strerror(errno != 0 ? errno : EIO));
        status = finish_temp("render", tmp_path, out_path, status);
        free(tmp_path);
    }
    free(png);
    if (status == 0)
        printf("points=%" PRIu64 " bytes=%zu\n", points, size);
    return status;
}

#define BENCH_USAGE "usage: gpstiles bench FILE.gpt"
#define BENCH_TILES 100 /* renders timed per zoom */

static int compare_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

/* gpstiles bench FILE.gpt: how fast tiles are drawn at each zoom (DESIGN §9.1), the way the server
 * draws them (count + color + PNG), without HTTP, one at a time, with the file already in memory. At each
 * zoom it renders the tiles of 100 points spread evenly through the file, so busy places are timed more
 * often, as a map user would ask for them; at low zooms that is the same 1 or 2 tiles again and again
 * (the `tiles` column says how many). Speed only, never pass/fail. */
static int cmd_bench(int argc, char **argv)
{
    if (argc < 2) {
        fputs("gpstiles bench: missing arguments (" BENCH_USAGE ")\n", stderr);
        return 2;
    }
    if (argv[1][0] == '-' || argc > 2)
        return bad_argument("bench", "argument", first_option(argc, argv, 2), BENCH_USAGE);
    struct tilefile tf;
    if (open_gpt("bench", argv[1], &tf) != 0)
        return 1;
    if (tf.header.count == 0) {
        tilefile_close(&tf);
        return file_error("bench", argv[1], "has no points to time");
    }
    printf("zoom renders tiles p50_ms p99_ms max_ms points_per_render\n");
    for (unsigned zoom = 0; zoom <= GEO_MAX_ZOOM; zoom++) {
        double ms[BENCH_TILES];
        struct geo_tile timed[BENCH_TILES];
        uint64_t points_total = 0;
        int distinct = 0;
        for (int k = 0; k < BENCH_TILES; k++) {
            struct geo_tile tile = geo_tile_of(tilefile_code(&tf, tf.header.count * (uint64_t)k / BENCH_TILES), zoom);
            int seen = 0;
            for (int j = 0; j < k && !seen; j++)
                seen = timed[j].x == tile.x && timed[j].y == tile.y;
            distinct += !seen;
            timed[k] = tile;
            struct timespec start, end;
            unsigned char *png;
            size_t size;
            uint64_t points;
            clock_gettime(CLOCK_MONOTONIC, &start);
            int failed = render_tile(&tf, zoom, tile.x, tile.y, &png, &size, &points);
            clock_gettime(CLOCK_MONOTONIC, &end);
            if (failed) {
                tilefile_close(&tf);
                fputs("gpstiles bench: out of memory\n", stderr);
                return 1;
            }
            free(png);
            ms[k] = (double)(end.tv_sec - start.tv_sec) * 1e3 + (double)(end.tv_nsec - start.tv_nsec) / 1e6;
            points_total += points;
        }
        qsort(ms, BENCH_TILES, sizeof ms[0], compare_double);
        printf("%u %d %d %.2f %.2f %.2f %" PRIu64 "\n", zoom, BENCH_TILES, distinct, ms[BENCH_TILES / 2 - 1],
               ms[(BENCH_TILES * 99 + 99) / 100 - 1], ms[BENCH_TILES - 1], points_total / BENCH_TILES);
    }
    tilefile_close(&tf);
    return 0;
}

#define SERVE_USAGE "usage: gpstiles serve [--host 127.0.0.1] [--port 8080] [--timeout 10] FILE.gpt..."

static int serve_error(const char *what, const char *arg, const char *want)
{
    return bad_argument("serve", what, arg, want);
}

/* gpstiles serve ...: opens every .gpt and serves them until killed (DESIGN §9.1, §9.2). A dataset's
 * id is its file name without .gpt. */
static int cmd_serve(int argc, char **argv)
{
    const char *host = "127.0.0.1";
    unsigned long port = 8080, timeout = SERVER_TIMEOUT_SECONDS;
    int i = 1;
    for (; i < argc && argv[i][0] == '-'; i++) {
        const char *option = argv[i];
        if (i + 1 >= argc)
            return serve_error("argument", option, SERVE_USAGE);
        const char *value = argv[++i];
        if (strcmp(option, "--host") == 0) {
            struct in_addr address;
            if (inet_pton(AF_INET, value, &address) != 1)
                return serve_error("--host", value, "want an IPv4 address such as 127.0.0.1");
            host = value;
        } else if (strcmp(option, "--port") == 0) {
            if (parse_whole(value, 65535, &port) != 0)
                return serve_error("--port", value, "want a port number from 0 to 65535 (0: any free port)");
        } else if (strcmp(option, "--timeout") == 0) {
            if (parse_whole(value, 3600, &timeout) != 0 || timeout == 0)
                return serve_error("--timeout", value, "want the seconds a client has to send its request, 1 to 3600");
        } else {
            return serve_error("argument", option, SERVE_USAGE);
        }
    }
    int count = argc - i;
    if (count == 0) {
        fputs("gpstiles serve: missing arguments (" SERVE_USAGE ")\n", stderr);
        return 2;
    }
    if (count > SERVER_MAX_DATASETS)
        return serve_error("argument", argv[i + SERVER_MAX_DATASETS], "at most 32 .gpt files");
    static struct dataset datasets[SERVER_MAX_DATASETS];
    for (int d = 0; d < count; d++) {
        const char *path = argv[i + d], *slash = strrchr(path, '/');
        const char *name = slash != NULL ? slash + 1 : path;
        size_t length = strlen(name);
        if (length < 5 || strcmp(name + length - 4, ".gpt") != 0 || length - 4 > SERVER_MAX_ID) {
            return serve_error("file name", path, "want NAME.gpt: its NAME, 1 to 32 of a-z 0-9 - _, is the dataset id");
        }
        memcpy(datasets[d].id, name, length - 4);
        datasets[d].id[length - 4] = '\0';
        if (!server_valid_id(datasets[d].id))
            return serve_error("file name", path, "want NAME.gpt: its NAME, 1 to 32 of a-z 0-9 - _, is the dataset id");
        for (int e = 0; e < d; e++) {
            if (strcmp(datasets[e].id, datasets[d].id) == 0)
                return serve_error("file name", path, "two files have the same dataset id");
        }
    }
    for (int d = 0; d < count; d++) {
        if (open_gpt("serve", argv[i + d], &datasets[d].file) != 0)
            return 1;
    }
    return server_run(host, (unsigned)port, (unsigned)timeout, datasets, (size_t)count);
}

/* The end of every command: if its printed result couldn't be written (stdout closed, disk full), the
 * command fails instead of reporting success. Returns status, or 1. */
static int finish_output(const char *command, int status)
{
    errno = 0;
    if (fflush(stdout) != 0 || ferror(stdout)) {
        fprintf(stderr, "gpstiles %s: can't write the result: %s\n", command, strerror(errno != 0 ? errno : EIO));
        return status == 0 ? 1 : status;
    }
    return status;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fputs("gpstiles: missing command (try 'gpstiles help')\n", stderr);
        return 2;
    }
    static const struct {
        const char *name;
        int (*run)(int argc, char **argv);
    } commands[] = {{"where", cmd_where}, {"import", cmd_import}, {"build", cmd_build}, {"info", cmd_info},
                    {"count", cmd_count}, {"render", cmd_render}, {"bench", cmd_bench}, {"serve", cmd_serve}};
    if (strcmp(argv[1], "help") == 0 || strcmp(argv[1], "--help") == 0) {
        print_usage();
        return finish_output("help", 0);
    }
    for (size_t i = 0; i < sizeof commands / sizeof commands[0]; i++) {
        if (strcmp(argv[1], commands[i].name) == 0)
            return finish_output(commands[i].name, commands[i].run(argc - 1, argv + 1));
    }
    char name[65];
    printable_copy(name, sizeof name, argv[1]);
    fprintf(stderr, "gpstiles: unknown command '%s' (try 'gpstiles help')\n", name);
    return 2;
}
