"""tools/stop-gate.sh, the Claude Code Stop hook (TESTING.md §12.2).

Each test copies the script into a temp git repo and swaps `make check` for a fake check
(STOP_GATE_CHECK), so these tests never run the real suite.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile

GATE = pathlib.Path(__file__).resolve().parents[2] / "tools" / "stop-gate.sh"
RED = "echo 'FAIL tests/unit/test_geo.c:57 tile_beijing_z10'; exit 1"
GREEN = "true"


def clean_env(**extra):
    """The environment without git's hook variables and the developer's git config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@localhost",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@localhost", **extra)
    return env


class Repo:
    """A temp git repo with tools/stop-gate.sh and one committed file in src/, docs/ and tests/."""

    def __init__(self, tmp):
        self.root = pathlib.Path(tmp)
        (self.root / "tools").mkdir()
        shutil.copy(GATE, self.root / "tools" / "stop-gate.sh")
        for path in ["src/main.c", "docs/notes.md", "tests/unit/test_a.c", "Makefile"]:
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("x\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=clean_env(), check=True, capture_output=True)

    def touch(self, path):
        with open(self.root / path, "a") as f:
            f.write("changed\n")

    def stop(self, check):
        """Runs the gate the way Claude Code does: JSON on stdin. Returns (exit code, stderr)."""
        result = subprocess.run([str(self.root / "tools" / "stop-gate.sh")], cwd=self.root,
                                input='{"hook_event_name":"Stop","stop_hook_active":false}',
                                env=clean_env(STOP_GATE_CHECK=check), capture_output=True, text=True, timeout=30)
        return result.returncode, result.stderr


def test_red_check_blocks_the_stop_and_shows_the_failure():
    """catches: the agent ends its turn while make check fails, or is blocked without seeing why"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        repo.touch("src/main.c")
        code, err = repo.stop(RED)
        assert code == 2, (code, err)
        assert "block 1 of 3" in err, err
        assert "FAIL tests/unit/test_geo.c:57 tile_beijing_z10" in err, err


def test_green_check_lets_the_agent_stop():
    """catches: the gate blocks even when make check passes, so the agent can never finish"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        repo.touch("src/main.c")
        assert repo.stop(GREEN) == (0, "")


def test_new_and_changed_code_files_all_trigger_the_check():
    """catches: a new untracked test file, a nested tests/ file or a Makefile edit is not seen as a change, so a red check slips past"""
    for path in ["tests/unit/test_new.c", "tests/unit/test_a.c", "Makefile", "src/new_module.c"]:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(tmp)
            repo.touch(path)
            assert repo.stop(RED)[0] == 2, path


def test_no_code_change_skips_the_check():
    """catches: the gate runs make check after doc-only edits, so a red check unrelated to the turn blocks it"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        assert repo.stop(RED)[0] == 0
        repo.touch("docs/notes.md")
        assert repo.stop(RED)[0] == 0


def test_three_blocks_in_a_row_then_the_agent_may_stop():
    """catches: the loop guard never lets go (endless loop), lets go too early, or skips the 'write Blocked on' message"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        repo.touch("src/main.c")
        codes = []
        for _ in range(3):
            code, err = repo.stop(RED)
            codes.append(code)
        assert codes == [2, 2, 2], codes
        assert "Blocked on" in err, err
        code, err = repo.stop(RED)
        assert code == 0, (code, err)
        assert "Letting the agent stop" in err, err
        assert repo.stop(RED)[0] == 2, "the count starts again after letting the agent stop"


def test_a_green_check_resets_the_count():
    """catches: blocks from an earlier, fixed problem count toward the limit, so a new failure is let through early"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        repo.touch("src/main.c")
        repo.stop(RED)
        repo.stop(RED)
        assert repo.stop(GREEN)[0] == 0
        code, err = repo.stop(RED)
        assert code == 2 and "block 1 of 3" in err, (code, err)
