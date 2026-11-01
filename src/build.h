/* build.h: .pts → sorted .gpt with an external merge sort, and the .gpt header (DESIGN §5.3, §9.3).
 * Codes are read in chunks, each chunk is sorted and written as a run to one temp file, and the
 * runs are merged into the output. Header stats are counted during the merge. */
#ifndef BUILD_H
#define BUILD_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "geo.h"

#define BUILD_MAGIC "GPSTILE"  /* 8 bytes with its '\0' */
#define BUILD_VERSION 1
#define BUILD_HEADER_SIZE 256
#define BUILD_MAX_RUNS 256     /* more → the caller should raise --mem */
#define BUILD_MERGE_CODES 8192 /* the merge reads each run through a window of at most 64 KiB, */
#define BUILD_MERGE_MIN 512     /* shrunk to chunk / runs (at least 4 KiB) to stay within --mem */

/* Stats are 0 when count is 0. A pixel at zoom z is 1/256 of a tile's side: the top 2(z+8) bits
 * of a code. The view box is the middle 90% of points on each axis (5% cut from each end), widened
 * to 65,536-unit histogram buckets. */
struct build_header {
    uint64_t count;
    uint32_t min_x, min_y, max_x, max_y;            /* exact bounds of all points */
    uint64_t max_pixel_count[GEO_MAX_ZOOM + 1];     /* densest pixel at each zoom */
    uint32_t view_min_x, view_min_y, view_max_x, view_max_y;
};

enum build_status {
    BUILD_OK,
    BUILD_NO_MEMORY,
    BUILD_READ_ERROR,    /* reading an input failed */
    BUILD_BAD_INPUT,     /* an input's size is not a multiple of 8 bytes */
    BUILD_GPT_INPUT,     /* an input starts with a .gpt header (build_is_gpt): a .gpt given as a .pts */
    BUILD_TOO_MANY_RUNS, /* more than BUILD_MAX_RUNS chunks */
    BUILD_TEMP_ERROR,    /* writing or reading the run file failed */
    BUILD_WRITE_ERROR    /* writing the output failed */
};

struct build;

/* Starts a build that sorts `chunk_codes` codes (≥ 1) at a time and keeps its runs in `runs`, an
 * empty file open for reading and writing (the caller closes it). Returns NULL if out of memory. */
struct build *build_start(size_t chunk_codes, FILE *runs);

/* Adds every code of one .pts stream (little-endian uint64s). */
enum build_status build_add(struct build *b, FILE *in);

/* Merges the runs into `out` (a new, seekable file): 256-byte header, then the sorted codes.
 * Fills *header and *runs_used. */
enum build_status build_finish(struct build *b, FILE *out, struct build_header *header, size_t *runs_used);

void build_free(struct build *b);

/* 1 if 16 bytes start a .gpt, finished or not: the label, version 1 (or 0 while a build is still
 * writing it, so a killed build's leftover is recognized too) and header size 256. */
int build_is_gpt(const unsigned char head[16]);

/* The 256-byte little-endian header (DESIGN §9.3): magic 0, version 8, header size 12, count 16,
 * bounds 24 (min x, min y, max x, max y), densest pixel per zoom 40, view box 240 (same order). */
void build_encode_header(const struct build_header *header, unsigned char out[BUILD_HEADER_SIZE]);

#endif
