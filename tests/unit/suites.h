/* suites.h: every unit-test suite. Each step adds its module's suite here and in main.c. */
#ifndef SUITES_H
#define SUITES_H

#include "check.h"

extern const struct check_case runner_cases[];
extern const size_t runner_cases_count;
extern const struct check_case geo_cases[];
extern const size_t geo_cases_count;
extern const struct check_case import_cases[];
extern const size_t import_cases_count;
extern const struct check_case build_cases[];
extern const size_t build_cases_count;
extern const struct check_case tilefile_cases[];
extern const size_t tilefile_cases_count;
extern const struct check_case render_cases[];
extern const size_t render_cases_count;
extern const struct check_case area_cases[];
extern const size_t area_cases_count;

#endif
