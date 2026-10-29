/* check.c: state and output of the tiny test runner declared in check.h. */
#include "check.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

static uint64_t seed = 1;
static const struct check_case *current;
static int current_failed;
static size_t passed;
static size_t failed;

int check_init(void)
{
    const char *text = getenv("TEST_SEED");
    if (text == NULL || text[0] == '\0')
        return 0;

    /* strtoull accepts "-1" and leading spaces; a seed must be plain digits. */
    for (const char *p = text; *p != '\0'; p++) {
        if (*p < '0' || *p > '9') {
            /* The bad value isn't echoed: it could hold newlines or terminal escape codes. */
            fputs("TEST_SEED must be a whole number (digits only)\n", stderr);
            return 2;
        }
    }
    errno = 0;
    unsigned long long value = strtoull(text, NULL, 10);
    if (errno == ERANGE) {
        fputs("TEST_SEED is too large (max 18446744073709551615)\n", stderr);
        return 2;
    }
    seed = (uint64_t)value;
    return 0;
}

uint64_t check_seed(void)
{
    return seed;
}

static uint64_t rand_state;

uint64_t check_rand(void)
{
    uint64_t z = (rand_state += 0x9E3779B97F4A7C15u);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static void print_failure_header(const char *file, int line)
{
    printf("FAIL %s:%d %s\n", file, line, current->name);
    printf("  catches: %s\n", current->catches);
}

void check_fail_(const char *file, int line, const char *message)
{
    print_failure_header(file, line);
    printf("  %s\n", message);
    printf("  seed=%" PRIu64 "\n", seed);
    current_failed = 1;
}

void check_fail_u64_(const char *file, int line, const char *expr, uint64_t expected, uint64_t got)
{
    print_failure_header(file, line);
    printf("  %s: expected %" PRIu64 "   got %" PRIu64 "\n", expr, expected, got);
    printf("  seed=%" PRIu64 "\n", seed);
    current_failed = 1;
}

void check_suite(const struct check_case *cases, size_t count)
{
    for (size_t i = 0; i < count; i++) {
        current = &cases[i];
        current_failed = 0;
        rand_state = seed;
        cases[i].fn();
        if (current_failed)
            failed++;
        else
            passed++;
    }
    current = NULL;
}

int check_report(const char *level)
{
    printf("%-10s %3zu passed %3zu failed\n", level, passed, failed);
    return failed == 0 ? 0 : 1;
}
