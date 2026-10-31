/* tilefile.h: reads a .gpt file (DESIGN §5.4, §9.3) and finds the slice of sorted points inside a
 * tile. The file is memory-mapped read-only, so opening even a huge file costs almost no RAM. Replace an
 * open .gpt only by renaming a new file over it (build does): rewriting it in place can crash a reader. */
#ifndef TILEFILE_H
#define TILEFILE_H

#include <stddef.h>
#include <stdint.h>

#include "build.h"

struct tilefile {
    struct build_header header;
    const unsigned char *points; /* header.count little-endian uint64 codes, sorted ascending */
    void *map;                   /* the mapping to unmap, or NULL (tilefile_check) */
    size_t size;                 /* bytes in the whole file */
};

enum tilefile_status {
    TILEFILE_OK,
    TILEFILE_OPEN_ERROR,   /* can't open or map it: errno says why */
    TILEFILE_NOT_REGULAR,  /* a folder, pipe or device */
    TILEFILE_NOT_GPT,      /* wrong label */
    TILEFILE_UNFINISHED,   /* version 0: written by a build that was stopped before the end */
    TILEFILE_BAD_VERSION,  /* a version this program can't read */
    TILEFILE_BAD_HEADER,   /* header size isn't 256 */
    TILEFILE_CUT_SHORT,    /* smaller than the header */
    TILEFILE_SIZE_MISMATCH, /* the size isn't 256 + 8 × count */
    TILEFILE_BAD_STATS      /* header stats that no build writes (tilefile_check) */
};

/* Checks that the `size` bytes at `data` are a .gpt and, if so, fills *tf (map NULL). Pure: no files.
 * Header stats must be possible: all 0 with no points; else min ≤ max for the bounds and the view box,
 * and 1 ≤ densest pixel ≤ count, never growing with the zoom. The points are trusted to be sorted (build
 * writes them so): an unsorted file gives wrong counts, never a read outside the data. */
enum tilefile_status tilefile_check(const unsigned char *data, size_t size, struct tilefile *tf);

/* Opens, maps and checks the .gpt at `path`. Only on TILEFILE_OK is *tf filled and the file left
 * mapped until tilefile_close. */
enum tilefile_status tilefile_open(const char *path, struct tilefile *tf);
void tilefile_close(struct tilefile *tf);

/* The i-th code, i < header.count. */
uint64_t tilefile_code(const struct tilefile *tf, uint64_t i);

/* Codes from `low` to `high` (both included) are codes *first .. *end - 1. */
void tilefile_range(const struct tilefile *tf, uint64_t low, uint64_t high, uint64_t *first, uint64_t *end);

/* The slice of tile zoom/x/y (zoom ≤ GEO_MAX_ZOOM, x and y < 2^zoom): the codes whose top 2 × zoom
 * bits are the tile's. */
void tilefile_tile(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y, uint64_t *first,
                   uint64_t *end);

#endif
