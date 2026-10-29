/* Unit tests for the test runner itself. Failure behavior is tested from outside,
 * in tests/e2e/test_check_runner.py, because a failing check here would fail the suite. */
#include "suites.h"

static void passing_checks_count_as_pass(void)
{
    CHECK(1 + 1 == 2);
    CHECK_EQ_U64(42, 40 + 2);
    CHECK_EQ_U64(UINT64_MAX, (uint64_t)0 - 1);
}

const struct check_case runner_cases[] = {
    {"passing_checks_count_as_pass", "the runner reports a passing check as a failure, so every build looks broken",
     passing_checks_count_as_pass},
};
const size_t runner_cases_count = sizeof runner_cases / sizeof runner_cases[0];
