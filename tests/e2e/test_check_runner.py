"""The C test runner (tests/check.h) must fail loudly, or every other test is worthless.

Runs tests/selftest/always_fails.c, a suite with 2 failing tests and 1 passing test.
"""
import os
import subprocess


def run_selftest(seed=None):
    env = dict(os.environ)
    env.pop("TEST_SEED", None)
    if seed is not None:
        env["TEST_SEED"] = seed
    return subprocess.run([os.environ["CHECK_SELFTEST_BIN"]], capture_output=True, text=True, env=env, timeout=10)


def test_failing_test_fails_the_run():
    """catches: the runner prints FAIL but exits 0, so make check and the commit hook let broken code through"""
    result = run_selftest()
    assert result.returncode == 1, result.returncode
    assert "selftest     1 passed   2 failed" in result.stdout, result.stdout


def test_failure_names_place_test_and_bug():
    """catches: a failure that doesn't say where, which test, or what bug it guards, so nobody can act on it"""
    out = run_selftest().stdout
    assert "FAIL tests/selftest/always_fails.c:7 fails_with_values" in out, out
    assert "  catches: selftest: expected-vs-got failure" in out, out


def test_failure_shows_expected_and_got():
    """catches: a value mismatch is reported without the two values, so the fix needs a debugger"""
    out = run_selftest().stdout
    assert "2 + 2: expected 3   got 4" in out, out
    assert "check failed: ready == 1" in out, out


def test_later_tests_run_after_a_failure():
    """catches: the first failure stops the whole suite, hiding every failure after it"""
    out = run_selftest().stdout
    assert "fails_with_condition" in out, out
    assert "1 passed" in out, out


def test_seed_is_reported_on_failure():
    """catches: a random-test failure can't be repeated because the seed isn't printed"""
    assert "seed=1" in run_selftest().stdout
    assert "seed=7" in run_selftest(seed="7").stdout


def test_bad_seed_is_rejected():
    """catches: a mistyped TEST_SEED silently falls back to 1, so the re-run is not the run you asked for"""
    for bad in ["abc", "-1", " 7", "99999999999999999999999", "7\nFAKE\x1b[31m"]:
        result = run_selftest(seed=bad)
        assert result.returncode == 2, (bad, result.returncode)
        assert len(result.stderr.splitlines()) == 1, (bad, result.stderr)
        assert result.stderr.startswith("TEST_SEED"), (bad, result.stderr)
        assert "\x1b" not in result.stderr, (bad, result.stderr)
