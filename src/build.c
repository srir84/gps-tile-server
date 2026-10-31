/* build.c: external merge sort and .gpt header, declared in build.h (DESIGN §5.3, §9.3). */
#define _POSIX_C_SOURCE 200809L /* fseeko and off_t with -std=c11: run files can pass 2 GB */

#include "build.h"

#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

#define HISTOGRAM_BUCKETS 65536 /* top 16 bits of x or y: ~600 m at the equator */
#define OUT_CODES 8192

struct build {
    FILE *runs;
    uint64_t *chunk;
    size_t chunk_codes, filled;
    uint64_t run_start[BUILD_MAX_RUNS], run_length[BUILD_MAX_RUNS]; /* in codes */
    size_t run_count;
    uint64_t total; /* codes written to the run file so far */
};

static uint64_t load_le64(const unsigned char *p)
{
    uint64_t value = 0;
    for (int i = 7; i >= 0; i--)
        value = (value << 8) | p[i];
    return value;
}

static void store_le64(unsigned char *p, uint64_t value)
{
    for (int i = 0; i < 8; i++)
        p[i] = (unsigned char)(value >> (8 * i));
}

static void store_le32(unsigned char *p, uint32_t value)
{
    for (int i = 0; i < 4; i++)
        p[i] = (unsigned char)(value >> (8 * i));
}

struct build *build_start(size_t chunk_codes, FILE *runs)
{
    if (chunk_codes == 0 || chunk_codes > SIZE_MAX / sizeof(uint64_t))
        return NULL;
    struct build *b = calloc(1, sizeof *b);
    if (b == NULL)
        return NULL;
    /* Pages are only used once filled, so a large --mem costs nothing on a small input. */
    b->chunk = malloc(chunk_codes * sizeof *b->chunk);
    if (b->chunk == NULL) {
        free(b);
        return NULL;
    }
    b->runs = runs;
    b->chunk_codes = chunk_codes;
    return b;
}

void build_free(struct build *b)
{
    if (b == NULL)
        return;
    free(b->chunk);
    free(b);
}

static int compare_codes(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y); /* never x - y: it overflows and the sign is wrong */
}

/* Sorts the codes in the chunk and appends them to the run file as one run. */
static enum build_status flush_run(struct build *b)
{
    if (b->filled == 0)
        return BUILD_OK;
    if (b->run_count == BUILD_MAX_RUNS)
        return BUILD_TOO_MANY_RUNS;
    qsort(b->chunk, b->filled, sizeof *b->chunk, compare_codes);
    if (fwrite(b->chunk, sizeof *b->chunk, b->filled, b->runs) != b->filled)
        return BUILD_TEMP_ERROR;
    b->run_start[b->run_count] = b->total;
    b->run_length[b->run_count] = b->filled;
    b->run_count++;
    b->total += b->filled;
    b->filled = 0;
    return BUILD_OK;
}

int build_is_gpt(const unsigned char head[16])
{
    uint64_t version_and_size = load_le64(head + 8); /* version in the low 32 bits */
    return memcmp(head, BUILD_MAGIC, 8) == 0 && version_and_size >> 32 == BUILD_HEADER_SIZE &&
           (uint32_t)version_and_size <= BUILD_VERSION;
}

/* Adds one code to the chunk, writing a run first if the chunk is full. */
static enum build_status add_code(struct build *b, uint64_t code)
{
    if (b->filled == b->chunk_codes) {
        enum build_status status = flush_run(b);
        if (status != BUILD_OK)
            return status;
    }
    b->chunk[b->filled++] = code;
    return BUILD_OK;
}

enum build_status build_add(struct build *b, FILE *in)
{
    /* The first 16 bytes are read on their own, so a .gpt is recognized whatever room the chunk has left. */
    unsigned char head[16];
    size_t got = fread(head, 1, sizeof head, in);
    if (got == sizeof head && build_is_gpt(head))
        return BUILD_GPT_INPUT;
    for (size_t i = 0; i + sizeof(uint64_t) <= got; i += sizeof(uint64_t)) {
        enum build_status status = add_code(b, load_le64(head + i));
        if (status != BUILD_OK)
            return status;
    }
    if (got < sizeof head) {
        if (ferror(in))
            return BUILD_READ_ERROR;
        return got % sizeof(uint64_t) == 0 ? BUILD_OK : BUILD_BAD_INPUT;
    }
    for (;;) {
        if (b->filled == b->chunk_codes) {
            enum build_status status = flush_run(b);
            if (status != BUILD_OK)
                return status;
        }
        unsigned char *space = (unsigned char *)(b->chunk + b->filled);
        size_t want = (b->chunk_codes - b->filled) * sizeof(uint64_t);
        got = fread(space, 1, want, in);
        size_t codes = got / sizeof(uint64_t);
        for (size_t i = 0; i < codes; i++) /* .pts is little-endian; the chunk is in this machine's order */
            b->chunk[b->filled + i] = load_le64(space + sizeof(uint64_t) * i);
        b->filled += codes;
        if (got < want) { /* fread stops short only at the end of the file or on an error */
            if (ferror(in))
                return BUILD_READ_ERROR;
            return got % sizeof(uint64_t) == 0 ? BUILD_OK : BUILD_BAD_INPUT;
        }
    }
}

/* One run during the merge: a window of up to `window` codes, refilled from the run file. */
struct run {
    uint64_t pos, left; /* next code to load from the file, and how many are still there */
    uint64_t *buf;
    size_t window, have, next;
};

static int run_load(struct run *r, FILE *runs)
{
    size_t n = r->left < r->window ? (size_t)r->left : r->window;
    r->next = 0;
    r->have = n;
    if (n == 0)
        return 0;
    if (fseeko(runs, (off_t)(r->pos * sizeof(uint64_t)), SEEK_SET) != 0 || fread(r->buf, sizeof(uint64_t), n, runs) != n)
        return -1;
    r->pos += n;
    r->left -= n;
    return 0;
}

static uint64_t front(const struct run *runs, size_t i)
{
    return runs[i].buf[runs[i].next];
}

/* Min-heap of run numbers, ordered by each run's next code. */
static void sift_down(size_t *heap, size_t n, const struct run *runs, size_t i)
{
    for (;;) {
        size_t smallest = i, left = 2 * i + 1, right = left + 1;
        if (left < n && front(runs, heap[left]) < front(runs, heap[smallest]))
            smallest = left;
        if (right < n && front(runs, heap[right]) < front(runs, heap[smallest]))
            smallest = right;
        if (smallest == i)
            return;
        size_t swap = heap[i];
        heap[i] = heap[smallest];
        heap[smallest] = swap;
        i = smallest;
    }
}

/* Header stats, counted one sorted code at a time. */
struct stats {
    struct build_header *h;
    uint64_t pixel[GEO_MAX_ZOOM + 1], same[GEO_MAX_ZOOM + 1]; /* current pixel per zoom, and its count so far */
    uint64_t *hist_x, *hist_y;
};

static void count_point(struct stats *s, uint64_t code)
{
    struct build_header *h = s->h;
    uint32_t x, y;
    geo_split(code, &x, &y);
    if (h->count == 0) {
        h->min_x = h->max_x = x;
        h->min_y = h->max_y = y;
    }
    h->min_x = x < h->min_x ? x : h->min_x;
    h->max_x = x > h->max_x ? x : h->max_x;
    h->min_y = y < h->min_y ? y : h->min_y;
    h->max_y = y > h->max_y ? y : h->max_y;
    s->hist_x[x >> 16]++;
    s->hist_y[y >> 16]++;
    /* Codes arrive sorted, so the points of one pixel arrive together. */
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++) {
        uint64_t pixel = code >> (48 - 2 * z); /* top 2(z + 8) bits */
        if (h->count > 0 && pixel == s->pixel[z]) {
            s->same[z]++;
        } else {
            s->pixel[z] = pixel;
            s->same[z] = 1;
        }
        if (s->same[z] > h->max_pixel_count[z])
            h->max_pixel_count[z] = s->same[z];
    }
    h->count++;
}

/* The histogram bucket holding the point of 0-based rank `rank` (rank < number of points). */
static uint32_t bucket_of_rank(const uint64_t *hist, uint64_t rank)
{
    uint64_t seen = 0;
    uint32_t bucket = 0;
    for (; bucket < HISTOGRAM_BUCKETS - 1; bucket++) {
        seen += hist[bucket];
        if (seen > rank)
            break;
    }
    return bucket;
}

static void set_view_box(struct build_header *h, const uint64_t *hist_x, const uint64_t *hist_y)
{
    uint64_t cut = h->count / 100; /* 1% from each end */
    h->view_min_x = bucket_of_rank(hist_x, cut) << 16;
    h->view_min_y = bucket_of_rank(hist_y, cut) << 16;
    h->view_max_x = bucket_of_rank(hist_x, h->count - 1 - cut) << 16 | 0xFFFF;
    h->view_max_y = bucket_of_rank(hist_y, h->count - 1 - cut) << 16 | 0xFFFF;
}

/* Merges every run into `out` (after the header's space), counting stats on the way. */
static enum build_status merge(struct build *b, FILE *out, struct stats *s)
{
    enum build_status status = BUILD_NO_MEMORY;
    size_t n = b->run_count;
    struct run *runs = calloc(n, sizeof *runs);
    size_t *heap = calloc(n, sizeof *heap);
    unsigned char *out_buf = malloc(OUT_CODES * sizeof(uint64_t));
    if (runs == NULL || heap == NULL || out_buf == NULL)
        goto done;
    /* The sort buffer is freed by now: the windows share its size, so memory stays near --mem. */
    size_t window = b->chunk_codes / n;
    window = window < BUILD_MERGE_MIN ? BUILD_MERGE_MIN : window > BUILD_MERGE_CODES ? BUILD_MERGE_CODES : window;
    for (size_t i = 0; i < n; i++) {
        runs[i].window = window;
        runs[i].buf = malloc(window * sizeof(uint64_t));
        if (runs[i].buf == NULL)
            goto done;
        runs[i].pos = b->run_start[i];
        runs[i].left = b->run_length[i];
        if (run_load(&runs[i], b->runs) != 0) {
            status = BUILD_TEMP_ERROR;
            goto done;
        }
        heap[i] = i;
    }
    for (size_t i = n / 2; i-- > 0;)
        sift_down(heap, n, runs, i);

    size_t used = 0;
    while (n > 0) {
        struct run *r = &runs[heap[0]];
        uint64_t code = r->buf[r->next];
        count_point(s, code);
        store_le64(out_buf + sizeof(uint64_t) * used++, code);
        if (used == OUT_CODES) {
            if (fwrite(out_buf, sizeof(uint64_t), used, out) != used) {
                status = BUILD_WRITE_ERROR;
                goto done;
            }
            used = 0;
        }
        if (++r->next == r->have) {
            if (run_load(r, b->runs) != 0) {
                status = BUILD_TEMP_ERROR;
                goto done;
            }
            if (r->have == 0) /* this run is used up */
                heap[0] = heap[--n];
        }
        sift_down(heap, n, runs, 0);
    }
    status = fwrite(out_buf, sizeof(uint64_t), used, out) == used ? BUILD_OK : BUILD_WRITE_ERROR;
done:
    if (runs != NULL) {
        for (size_t i = 0; i < b->run_count; i++)
            free(runs[i].buf);
    }
    free(runs);
    free(heap);
    free(out_buf);
    return status;
}

enum build_status build_finish(struct build *b, FILE *out, struct build_header *header, size_t *runs_used)
{
    enum build_status status = flush_run(b);
    if (status != BUILD_OK)
        return status;
    free(b->chunk); /* the merge needs only small buffers */
    b->chunk = NULL;
    *runs_used = b->run_count;
    memset(header, 0, sizeof *header);
    if (fflush(b->runs) != 0)
        return BUILD_TEMP_ERROR;

    /* Space for the header, written last. Until then it is an "unfinished" header (version 0), so a
     * killed build's leftover is never taken for points (build_is_gpt) or for a finished .gpt. */
    unsigned char bytes[BUILD_HEADER_SIZE] = {0};
    build_encode_header(header, bytes);
    memset(bytes + 8, 0, 4);
    if (fwrite(bytes, 1, sizeof bytes, out) != sizeof bytes)
        return BUILD_WRITE_ERROR;
    if (b->run_count > 0) {
        struct stats s = {header, {0}, {0}, calloc(HISTOGRAM_BUCKETS, sizeof(uint64_t)),
                          calloc(HISTOGRAM_BUCKETS, sizeof(uint64_t))};
        status = s.hist_x != NULL && s.hist_y != NULL ? merge(b, out, &s) : BUILD_NO_MEMORY;
        if (status == BUILD_OK)
            set_view_box(header, s.hist_x, s.hist_y);
        free(s.hist_x);
        free(s.hist_y);
        if (status != BUILD_OK)
            return status;
    }
    build_encode_header(header, bytes);
    if (fseeko(out, 0, SEEK_SET) != 0 || fwrite(bytes, 1, sizeof bytes, out) != sizeof bytes || fflush(out) != 0)
        return BUILD_WRITE_ERROR;
    return BUILD_OK;
}

void build_encode_header(const struct build_header *h, unsigned char out[BUILD_HEADER_SIZE])
{
    memset(out, 0, BUILD_HEADER_SIZE);
    memcpy(out, BUILD_MAGIC, 8);
    store_le32(out + 8, BUILD_VERSION);
    store_le32(out + 12, BUILD_HEADER_SIZE);
    store_le64(out + 16, h->count);
    store_le32(out + 24, h->min_x);
    store_le32(out + 28, h->min_y);
    store_le32(out + 32, h->max_x);
    store_le32(out + 36, h->max_y);
    for (unsigned z = 0; z <= GEO_MAX_ZOOM; z++)
        store_le64(out + 40 + 8 * z, h->max_pixel_count[z]);
    store_le32(out + 240, h->view_min_x);
    store_le32(out + 244, h->view_min_y);
    store_le32(out + 248, h->view_max_x);
    store_le32(out + 252, h->view_max_y);
}
