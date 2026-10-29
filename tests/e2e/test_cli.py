"""The gpstiles command line: exit codes and messages scripts rely on (TESTING.md §10)."""
import os
import subprocess


def run(*args):
    return subprocess.run([os.environ["GPSTILES_BIN"], *args], capture_output=True, text=True, timeout=10)


def test_help_succeeds_on_stdout():
    """catches: `gpstiles help` exits non-zero or prints to stderr, so scripts think help failed"""
    result = run("help")
    assert result.returncode == 0, result.returncode
    assert result.stdout.startswith("usage: gpstiles"), result.stdout
    assert result.stderr == "", result.stderr


def test_no_command_is_a_one_line_usage_error():
    """catches: running gpstiles with no command exits 0 or prints a multi-line message, so a broken script looks successful"""
    result = run()
    assert result.returncode == 2, result.returncode
    lines = result.stderr.splitlines()
    assert len(lines) == 1, lines
    assert "missing command" in lines[0], lines[0]
    assert result.stdout == "", result.stdout


def test_unknown_command_is_one_line_error():
    """catches: a mistyped command exits 0 or floods the screen instead of one clear line"""
    result = run("biuld")
    assert result.returncode == 2, result.returncode
    lines = result.stderr.splitlines()
    assert len(lines) == 1, lines
    assert "unknown command 'biuld'" in lines[0], lines[0]
    assert result.stdout == "", result.stdout


def test_unknown_command_name_is_cut_short():
    """catches: a huge command name is echoed in full, so the 'one-line message' rule breaks"""
    result = run("x" * 5000)
    assert result.returncode == 2, result.returncode
    assert len(result.stderr) < 200, len(result.stderr)


def test_control_characters_in_name_stay_on_one_line():
    """catches: a command name with a newline or escape code splits the error or sends codes to the terminal"""
    result = run("bad\ncommand\x1b[31m")
    assert result.returncode == 2, result.returncode
    lines = result.stderr.splitlines()
    assert len(lines) == 1, lines
    assert "unknown command 'bad?command?[31m'" in lines[0], lines[0]
