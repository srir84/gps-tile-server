/* Unit test entry point: runs every suite in suites.h and prints one summary line. */
#include "check.h"
#include "suites.h"

int main(void)
{
    int status = check_init();
    if (status != 0)
        return status;

    check_suite(runner_cases, runner_cases_count);
    check_suite(geo_cases, geo_cases_count);
    check_suite(import_cases, import_cases_count);
    check_suite(build_cases, build_cases_count);
    check_suite(tilefile_cases, tilefile_cases_count);
    check_suite(render_cases, render_cases_count);
    check_suite(area_cases, area_cases_count);
    return check_report("unit");
}
