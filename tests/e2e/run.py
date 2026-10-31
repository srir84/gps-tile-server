"""Runs every test_* function in tests/e2e/test_*.py and prints one summary line.

Each test's docstring must start with "catches:" (TESTING.md §4); a test without one fails.
A file with no tests, no test files at all, or a test that calls sys.exit also fail, so
tests can't disappear or end the run early without it showing. A test that can't run here
(e.g. no Chrome) returns "SKIPPED: why": printed and counted apart, never as passed.
Run by `make check` with GPSTILES_BIN and CHECK_SELFTEST_BIN set. Exit code 0 = all passed.
Optional argument: the folder to search (default: this folder). Used by test_e2e_runner.py.
"""
import importlib.util
import inspect
import pathlib
import sys
import traceback

HERE = pathlib.Path(__file__).resolve().parent


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(where, name, lines):
    print(f"FAIL {where} {name}")
    for line in lines:
        print(f"  {line}")


def run_one(path, name, test):
    """Returns "passed", "failed" or "skipped". Prints a failure or a skip."""
    doc = (test.__doc__ or "").strip()
    if not doc.startswith("catches:"):
        report(path.name, name, ["test has no 'catches:' docstring"])
        return "failed"
    # Calling these only creates a generator or coroutine; the body would never run.
    if inspect.isgeneratorfunction(test) or inspect.iscoroutinefunction(test) or inspect.isasyncgenfunction(test):
        report(path.name, name, ["test must be a plain function (no yield, no async), or its body never runs"])
        return "failed"
    try:
        result = test()
    except (Exception, SystemExit) as error:  # SystemExit too: sys.exit(0) in a test must not end the run
        frame = traceback.extract_tb(error.__traceback__)[-1]
        report(f"{pathlib.Path(frame.filename).name}:{frame.lineno}", name,
               [doc.splitlines()[0], f"{type(error).__name__}: {error}"])
        return "failed"
    if isinstance(result, str) and result.startswith("SKIPPED: "):
        print(f"SKIP {path.name} {name}: {result[9:]}")
        return "skipped"
    return "passed"


def main(folder):
    passed = failed = skipped = 0
    paths = sorted(folder.glob("test_*.py"))
    if not paths:
        report(str(folder), "(discovery)", ["no test_*.py files found"])
        failed += 1
    for path in paths:
        try:
            module = load(path)
        except (Exception, SystemExit) as error:
            report(path.name, "(import)", [f"{type(error).__name__}: {error}"])
            failed += 1
            continue
        names = sorted(n for n in dir(module) if n.startswith("test_") and callable(getattr(module, n)))
        if not names:
            report(path.name, "(discovery)", ["file has no test_* functions"])
            failed += 1
        for name in names:
            outcome = run_one(path, name, getattr(module, name))
            passed += outcome == "passed"
            failed += outcome == "failed"
            skipped += outcome == "skipped"
    print(f"{'e2e':<10} {passed:3d} passed {failed:3d} failed" + (f" {skipped:3d} skipped" if skipped else ""))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE))
