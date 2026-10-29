/* check.h: tiny C test runner (TESTING.md §3–§5).
 * A test is a void function plus the real bug it catches. A failed CHECK prints
 * file:line, the test name, its "catches:" label and the seed, then ends that test. */
#ifndef CHECK_H
#define CHECK_H

#include <stddef.h>
#include <stdint.h>

struct check_case {
    const char *name;
    const char *catches; /* the real bug this test would find */
    void (*fn)(void);
};

/* Reads TEST_SEED (default 1). Returns 0, or 2 after printing why the value is bad. */
int check_init(void);

/* Seed for random tests, from TEST_SEED. */
uint64_t check_seed(void);

/* Next random number (splitmix64). Restarts from the seed before each test, so a failing
 * test repeats exactly with the same TEST_SEED, whatever ran before it. */
uint64_t check_rand(void);

/* Runs every case in order. A failure ends only that case; the rest still run. */
void check_suite(const struct check_case *cases, size_t count);

/* Prints "<level> N passed M failed" and returns 0 if nothing failed, else 1. */
int check_report(const char *level);

void check_fail_(const char *file, int line, const char *message);
void check_fail_u64_(const char *file, int line, const char *expr, uint64_t expected, uint64_t got);

/* These return from the calling test, so test functions must return void. */
#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            check_fail_(__FILE__, __LINE__, "check failed: " #cond);    \
            return;                                                     \
        }                                                               \
    } while (0)

#define CHECK_EQ_U64(expected, got)                                         \
    do {                                                                    \
        uint64_t check_e_ = (expected), check_g_ = (got);                   \
        if (check_e_ != check_g_) {                                         \
            check_fail_u64_(__FILE__, __LINE__, #got, check_e_, check_g_);  \
            return;                                                         \
        }                                                                   \
    } while (0)

#endif
