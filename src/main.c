/* gpstiles: command-line entry point. Commands are added step by step (DESIGN §9.1).
 * Exit codes: 0 = ok, 1 = a file can't be read or written, 2 = usage error (unknown command,
 * bad arguments). Errors are one line on stderr. */
#define _POSIX_C_SOURCE 200809L /* stat, mkstemp, fdopen with -std=c11 */

#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "build.h"
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
          "                           read text rows into a .pts file and print what was kept and skipped\n"
          "  build [--mem SIZE] [--tmp DIR] -o OUT.gpt IN.pts...\n"
          "                           sort the points into a .gpt tile file\n",
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
            if (value[0] == '\0')
                return import_error("-o", value, "want a file name");
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
    FILE *out = open_temp_beside("import", out_path, &tmp_path);
    if (out == NULL)
        return 1;
    struct import_counts counts = {0, 0, 0, 0, 0};
    int status = import_files(files, file_count, out_path, out, &options, &counts);
    errno = 0;
    if (fclose(out) != 0 && status == 0)
        status = file_error("import", out_path, strerror(errno != 0 ? errno : EIO));
    status = finish_temp("import", tmp_path, out_path, status);
    free(tmp_path);
    if (status != 0)
        return status;
    printf("rows=%" PRIu64 " imported=%" PRIu64 " skipped_zero=%" PRIu64 " skipped_out_of_range=%" PRIu64
           " skipped_malformed=%" PRIu64 "\n",
           counts.rows, counts.imported, counts.skipped_zero, counts.skipped_out_of_range, counts.skipped_malformed);
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
    if (strcmp(argv[1], "build") == 0)
        return cmd_build(argc - 1, argv + 1);
    char name[65];
    printable_copy(name, sizeof name, argv[1]);
    fprintf(stderr, "gpstiles: unknown command '%s' (try 'gpstiles help')\n", name);
    return 2;
}
