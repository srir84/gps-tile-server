/* tilefile.c: reading a .gpt and finding slices, declared in tilefile.h (DESIGN §5.4, §9.3). */
#define _POSIX_C_SOURCE 200809L /* open, fstat, mmap with -std=c11 */

#include "tilefile.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static uint32_t load_le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint64_t load_le64(const unsigned char *p)
{
    return (uint64_t)load_le32(p) | (uint64_t)load_le32(p + 4) << 32;
}

/* 1 if the stats could have been written by build (tilefile.h). */
static int stats_possible(const struct build_header *h)
{
    if (h->count == 0) {
        uint64_t any = (uint64_t)h->min_x | h->min_y | h->max_x | h->max_y | h->view_min_x | h->view_min_y |
                       h->view_max_x | h->view_max_y;
        for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
            any |= h->max_pixel_count[z];
        return any == 0;
    }
    if (h->min_x > h->max_x || h->min_y > h->max_y || h->view_min_x > h->view_max_x || h->view_min_y > h->view_max_y)
        return 0;
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++) {
        uint64_t m = h->max_pixel_count[z]; /* a pixel at zoom z + 1 is a quarter of one at zoom z */
        if (m < 1 || m > h->count || (z > 0 && m > h->max_pixel_count[z - 1]))
            return 0;
    }
    return 1;
}

enum tilefile_status tilefile_check(const unsigned char *data, size_t size, struct tilefile *tf)
{
    if (size < 8 || memcmp(data, BUILD_MAGIC, 8) != 0)
        return TILEFILE_NOT_GPT;
    if (size < BUILD_HEADER_SIZE)
        return TILEFILE_CUT_SHORT;
    if (load_le32(data + 8) != BUILD_VERSION)
        return load_le32(data + 8) == 0 ? TILEFILE_UNFINISHED : TILEFILE_BAD_VERSION;
    if (load_le32(data + 12) != BUILD_HEADER_SIZE)
        return TILEFILE_BAD_HEADER;
    uint64_t count = load_le64(data + 16);
    if (count > (size - BUILD_HEADER_SIZE) / 8 || size - BUILD_HEADER_SIZE != count * 8)
        return TILEFILE_SIZE_MISMATCH; /* the first test keeps count * 8 from overflowing */
    struct build_header *h = &tf->header;
    h->count = count;
    h->min_x = load_le32(data + 24);
    h->min_y = load_le32(data + 28);
    h->max_x = load_le32(data + 32);
    h->max_y = load_le32(data + 36);
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        h->max_pixel_count[z] = load_le64(data + 40 + 8 * z);
    h->view_min_x = load_le32(data + 240);
    h->view_min_y = load_le32(data + 244);
    h->view_max_x = load_le32(data + 248);
    h->view_max_y = load_le32(data + 252);
    if (!stats_possible(h))
        return TILEFILE_BAD_STATS;
    tf->points = data + BUILD_HEADER_SIZE;
    tf->map = NULL;
    tf->size = size;
    return TILEFILE_OK;
}

/* Closes fd, keeping errno, and returns status. */
static enum tilefile_status close_with(int fd, enum tilefile_status status)
{
    int error = errno;
    close(fd);
    errno = error;
    return status;
}

enum tilefile_status tilefile_open(const char *path, struct tilefile *tf)
{
    /* O_NONBLOCK: opening a named pipe must not wait for a writer. It doesn't affect regular files. */
    int fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return TILEFILE_OPEN_ERROR;
    struct stat st;
    if (fstat(fd, &st) != 0)
        return close_with(fd, TILEFILE_OPEN_ERROR);
    if (!S_ISREG(st.st_mode))
        return close_with(fd, TILEFILE_NOT_REGULAR);
    size_t size = (size_t)st.st_size;
    if (size < BUILD_HEADER_SIZE) { /* too small to be worth mapping: read it to say what is wrong */
        unsigned char head[BUILD_HEADER_SIZE];
        ssize_t got = read(fd, head, sizeof head);
        if (got < 0)
            return close_with(fd, TILEFILE_OPEN_ERROR);
        close(fd);
        return tilefile_check(head, (size_t)got, tf);
    }
    void *map = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (map == MAP_FAILED)
        return close_with(fd, TILEFILE_OPEN_ERROR);
    close(fd); /* the mapping stays valid */
    enum tilefile_status status = tilefile_check(map, size, tf);
    if (status != TILEFILE_OK) {
        munmap(map, size);
        return status;
    }
    tf->map = map;
    return TILEFILE_OK;
}

void tilefile_close(struct tilefile *tf)
{
    if (tf->map != NULL)
        munmap(tf->map, tf->size);
    tf->map = NULL;
}

uint64_t tilefile_code(const struct tilefile *tf, uint64_t i)
{
    return load_le64(tf->points + 8 * i);
}

/* The index of the first code ≥ value, or count if there is none. */
static uint64_t lower_bound(const struct tilefile *tf, uint64_t value)
{
    uint64_t low = 0, high = tf->header.count;
    while (low < high) {
        uint64_t middle = low + (high - low) / 2;
        if (tilefile_code(tf, middle) < value)
            low = middle + 1;
        else
            high = middle;
    }
    return low;
}

void tilefile_range(const struct tilefile *tf, uint64_t low, uint64_t high, uint64_t *first, uint64_t *end)
{
    *first = lower_bound(tf, low);
    *end = high == UINT64_MAX ? tf->header.count : lower_bound(tf, high + 1);
    if (*end < *first) /* low > high */
        *end = *first;
}

void tilefile_tile(const struct tilefile *tf, unsigned zoom, uint32_t x, uint32_t y, uint64_t *first,
                   uint64_t *end)
{
    /* The tile's codes share their top 2 × zoom bits: the tile's corner, with every lower bit 0 to 1. */
    uint64_t low = geo_code((uint32_t)((uint64_t)x << (32 - zoom)), (uint32_t)((uint64_t)y << (32 - zoom)));
    tilefile_range(tf, low, low | (UINT64_MAX >> (2 * zoom)), first, end);
}
