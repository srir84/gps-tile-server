/* suites.h: every unit-test suite. Each step adds its module's suite here and in main.c. */
#ifndef SUITES_H
#define SUITES_H

#include "check.h"

extern const struct check_case runner_cases[];
extern const size_t runner_cases_count;
extern const struct check_case geo_cases[];
extern const size_t geo_cases_count;

#endif
