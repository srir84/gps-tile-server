/* Unit test entry point: runs every suite in suites.h and prints one summary line. */
#include "check.h"
#include "suites.h"

int main(void)
{
    int status = check_init();
    if (status != 0)
        return status;

    check_suite(runner_cases, runner_cases_count);
    return check_report("unit");
}
