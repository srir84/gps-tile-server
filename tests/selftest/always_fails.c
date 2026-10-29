/* always_fails.c: a suite that fails on purpose. tests/e2e/test_check_runner.py runs it
 * to prove a failing test makes the run fail, so `make check` can't pass broken code. */
#include "check.h"

static void fails_with_values(void)
{
    CHECK_EQ_U64(3, 2 + 2);
}

static void fails_with_condition(void)
{
    int ready = 0;
    CHECK(ready == 1);
}

static void passes_after_failures(void)
{
    CHECK(1);
}

static const struct check_case cases[] = {
    {"fails_with_values", "selftest: expected-vs-got failure", fails_with_values},
    {"fails_with_condition", "selftest: condition failure", fails_with_condition},
    {"passes_after_failures", "selftest: later tests still run", passes_after_failures},
};

int main(void)
{
    int status = check_init();
    if (status != 0)
        return status;

    check_suite(cases, sizeof cases / sizeof cases[0]);
    return check_report("selftest");
}
