/* Unit tests for the test runner itself. Failure behavior is tested from outside,
 * in tests/e2e/test_check_runner.py, because a failing check here would fail the suite. */
#include "suites.h"

static void passing_checks_count_as_pass(void)
{
    CHECK(1 + 1 == 2);
    CHECK_EQ_U64(42, 40 + 2);
    CHECK_EQ_U64(UINT64_MAX, (uint64_t)0 - 1);
}

/* These two run in order: the second must see the same first number as the first. */
static uint64_t first_number;

static void random_numbers_start_from_the_seed(void)
{
    first_number = check_rand();
    CHECK(check_rand() != first_number);
}

static void random_numbers_restart_for_each_test(void)
{
    CHECK_EQ_U64(first_number, check_rand());
}

const struct check_case runner_cases[] = {
    {"passing_checks_count_as_pass", "the runner reports a passing check as a failure, so every build looks broken",
     passing_checks_count_as_pass},
    {"random_numbers_start_from_the_seed", "check_rand returns the same number every time, so random tests test one case",
     random_numbers_start_from_the_seed},
    {"random_numbers_restart_for_each_test",
     "random numbers carry over between tests, so re-running one failing test with its seed doesn't repeat the failure",
     random_numbers_restart_for_each_test},
};
const size_t runner_cases_count = sizeof runner_cases / sizeof runner_cases[0];
