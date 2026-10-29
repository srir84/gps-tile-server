"""The Python test runner (tests/e2e/run.py) must fail loudly, like the C one.

Each test writes small test files into a temp folder and runs run.py on that folder.
"""
import pathlib
import subprocess
import sys
import tempfile

RUN_PY = pathlib.Path(__file__).resolve().parent / "run.py"


def run_on(files):
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in files.items():
            (pathlib.Path(tmp) / name).write_text(text)
        return subprocess.run([sys.executable, "-I", "-B", str(RUN_PY), tmp],
                              capture_output=True, text=True, timeout=30)


GOOD = 'def test_ok():\n    """catches: x"""\n'


def test_good_folder_passes():
    """catches: the runner fails a folder of passing tests, so every build looks broken"""
    result = run_on({"test_a.py": GOOD})
    assert result.returncode == 0, result.stdout
    assert "1 passed   0 failed" in result.stdout, result.stdout


def test_sys_exit_zero_in_a_test_fails():
    """catches: a test calling sys.exit(0) ends the run early and reports success"""
    bad = 'import sys\ndef test_quits():\n    """catches: x"""\n    sys.exit(0)\n'
    result = run_on({"test_a.py": bad, "test_b.py": GOOD})
    assert result.returncode == 1, result.stdout
    assert "1 passed   1 failed" in result.stdout, result.stdout


def test_sys_exit_zero_on_import_fails():
    """catches: a test file calling sys.exit(0) while loading ends the run and reports success"""
    result = run_on({"test_a.py": "import sys\nsys.exit(0)\n", "test_b.py": GOOD})
    assert result.returncode == 1, result.stdout
    assert "(import)" in result.stdout, result.stdout


def test_no_test_files_fails():
    """catches: renamed or deleted test files make the run pass with nothing tested"""
    result = run_on({"helper.py": GOOD})
    assert result.returncode == 1, result.stdout
    assert "no test_*.py files found" in result.stdout, result.stdout


def test_file_without_tests_fails():
    """catches: test functions renamed without the test_ prefix are skipped silently"""
    result = run_on({"test_a.py": 'def check_ok():\n    """catches: x"""\n'})
    assert result.returncode == 1, result.stdout
    assert "file has no test_* functions" in result.stdout, result.stdout


def test_generator_and_async_tests_fail():
    """catches: a test with yield or async def counts as passed without its body ever running"""
    gen = 'def test_gen():\n    """catches: x"""\n    assert False\n    yield\n'
    coro = 'async def test_coro():\n    """catches: x"""\n    assert False\n'
    result = run_on({"test_a.py": gen, "test_b.py": coro})
    assert result.returncode == 1, result.stdout
    assert "0 passed   2 failed" in result.stdout, result.stdout


def test_missing_catches_label_fails():
    """catches: a test without a 'catches:' label slips in, breaking the TESTING.md rule"""
    result = run_on({"test_a.py": "def test_ok():\n    pass\n"})
    assert result.returncode == 1, result.stdout
    assert "no 'catches:' docstring" in result.stdout, result.stdout
