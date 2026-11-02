"""tools/review.sh, the Codex review step (TESTING.md §12.3).

Each test copies the script into a temp git repo and swaps codex for a fake (CODEX_BIN) that
saves its arguments and prompt, so these tests never call the real Codex.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REVIEW = pathlib.Path(__file__).resolve().parents[2] / "tools" / "review.sh"

FAKE_CODEX = """#!{python} -I
import json, pathlib, sys, time
here = pathlib.Path(sys.argv[0]).parent
(here / "args.json").write_text(json.dumps(sys.argv[1:]))
(here / "prompt.txt").write_text(sys.stdin.read())
if (here / "crash").exists():
    sys.exit(1)
if (here / "slow").exists():
    time.sleep(1.5)
out = sys.argv[sys.argv.index("-o") + 1]
summary = "" if (here / "no-summary").exists() else "SUMMARY: high=0 medium=1 low=0\\n"
pathlib.Path(out).write_text("1. medium src/new.c:1 example finding\\n" + summary)
"""

# Rows are read from DESIGN §12 and TESTING §9 only: the other tables' rows (here "| 12 |") are not steps.
DESIGN = ("## 9. Interfaces\n| 12 | header_size | uint32 | 256 |\n## 12. Build plan\n"
          "| 0b Loop tools | plain-English row |\n| 0b | `make verify` exact-check row | x | y |\n| 1 | geo | x | y |\n"
          "| 10 GeoLife | geolife plain row |\n| 10 | geolife exact-check row | x | y |\n## 13. Facts\n| 12 | a fact |\n")
TESTING = ("## 9. Tests added in each step\n| 0b | none | failing test caught by every guard |\n| 1 | geo tests | x |\n"
           "| 10 | geolife tests | x |\n## 10. Other\n| 12 | not a step |\n")


def clean_env(**extra):
    """The environment without git's hook variables and the developer's git config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@localhost",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@localhost", **extra)
    return env


class Repo:
    """A temp repo with one commit, then a step's changes: an edit, a new file, builder notes."""

    def __init__(self, tmp, docs=None):
        self.root = pathlib.Path(tmp) / "repo"
        self.fake = pathlib.Path(tmp) / "fake"
        self.fake.mkdir()
        (self.fake / "codex").write_text(FAKE_CODEX.format(python=sys.executable))
        (self.fake / "codex").chmod(0o755)
        files = {"tools/review.sh": None, "docs/DESIGN.md": DESIGN, "docs/TESTING.md": TESTING,
                 "AGENTS.md": "rules\n", "PROGRESS.md": "status\n", ".gitignore": ".review/\n", **(docs or {})}
        for path, text in files.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            if text is None:
                shutil.copy(REVIEW, self.root / path)
            else:
                (self.root / path).write_text(text)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        (self.root / "AGENTS.md").write_text("rules, edited in this step\n")
        (self.root / "src").mkdir()
        (self.root / "src" / "new.c").write_text("int brand_new_function(void);\n")
        (self.root / "docs" / "steps").mkdir()
        (self.root / "docs" / "steps" / "step-0b.md").write_text("BUILDER SAYS: all good\n")
        (self.root / "PROGRESS.md").write_text("BUILDER STATUS: waiting for review\n")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=clean_env(), check=True,
                              capture_output=True, text=True).stdout

    def review(self, step="0b"):
        return subprocess.run([str(self.root / "tools" / "review.sh"), step], cwd=self.root,
                              env=clean_env(CODEX_BIN=str(self.fake / "codex")),
                              capture_output=True, text=True, timeout=30)

    def start_review(self):
        """Starts a review without waiting for it."""
        return subprocess.Popen([str(self.root / "tools" / "review.sh"), "0b"], cwd=self.root,
                                env=clean_env(CODEX_BIN=str(self.fake / "codex")),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def round_file(self, name):
        return (self.root / ".review" / "step-0b" / name).read_text()


def test_diff_has_new_files_but_not_the_builders_notes():
    """catches: new (untracked) files are missing from the review, or the builder's own summary steers the reviewer"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        result = repo.review()
        assert result.returncode == 0, result.stderr
        diff = repo.round_file("round-1.diff")
        assert "brand_new_function" in diff, diff
        assert "rules, edited in this step" in diff, diff
        assert "BUILDER" not in diff, diff


def test_real_index_is_left_alone():
    """catches: review.sh stages files in the real index, so the next commit quietly contains more than intended"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        before = repo.git("status", "--porcelain")
        assert repo.review().returncode == 0
        assert repo.git("status", "--porcelain") == before
        assert repo.git("diff", "--cached", "--name-only") == ""


def test_codex_is_read_only_and_told_what_the_step_must_do():
    """catches: Codex runs with write access, or reviews without the step's DESIGN and TESTING rows"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        result = repo.review()
        assert result.returncode == 0, result.stderr
        args = json.loads((repo.fake / "args.json").read_text())
        assert args[0] == "exec" and args[args.index("-s") + 1] == "read-only", args
        prompt = (repo.fake / "prompt.txt").read_text()
        assert "`make verify` exact-check row" in prompt and "plain-English row" in prompt, prompt
        assert "failing test caught by every guard" in prompt, prompt
        assert "geo" not in prompt, "rows of other steps leaked in"
        assert "SUMMARY: high=0 medium=1 low=0" in result.stdout, result.stdout


def test_round_two_checks_round_one_and_round_three_is_refused():
    """catches: unlimited review rounds, or round 2 never asked whether round-1 findings were fixed"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        assert repo.review().returncode == 0
        assert repo.review().returncode == 0
        assert "round-1.md" in (repo.fake / "prompt.txt").read_text()
        assert repo.round_file("round-1.md") and repo.round_file("round-2.md")
        third = repo.review()
        assert third.returncode == 1, third.returncode
        assert "2 review rounds" in third.stderr, third.stderr


def test_failed_codex_run_does_not_use_up_a_round():
    """catches: a crashed or offline Codex run counts as round 1, so a real review is skipped"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        (repo.fake / "crash").write_text("")
        result = repo.review()
        assert result.returncode == 1, result.returncode
        assert not (repo.root / ".review" / "step-0b" / "round-1.md").exists()
        (repo.fake / "crash").unlink()
        assert repo.review().returncode == 0
        assert "This is round 2" not in (repo.fake / "prompt.txt").read_text()


def test_bad_or_unknown_step_names_are_refused():
    """catches: a step name like ../x is used in a path and writes outside .review/, or a typo reviews with no step rows"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        for step in ["../x", "", "0b; rm -rf /", "12", "7"]:
            result = repo.review(step)
            assert result.returncode == 2, (step, result.returncode)
        assert not (repo.fake / "args.json").exists(), "codex ran for a bad step name"


def test_two_digit_steps_get_their_own_rows():
    """catches: stage 2's steps (10, 11) refused as bad names, or step 1's review given step 10's rows (or the reverse)"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        result = repo.review("10")
        assert result.returncode == 0, result.stderr
        prompt = (repo.fake / "prompt.txt").read_text()
        assert "geolife plain row" in prompt and "geolife exact-check row" in prompt and "geolife tests" in prompt, prompt
        assert "| 1 | geo |" not in prompt and "geo tests" not in prompt, "step 1's rows leaked into step 10's review"
        assert (repo.root / ".review" / "step-10" / "round-1.md").exists()
        result = repo.review("1")
        assert result.returncode == 0, result.stderr
        assert "geolife" not in (repo.fake / "prompt.txt").read_text(), "step 10's rows leaked into step 1's review"
        for step in ["100", "05", "1x0", "12"]:  # 12: rows only outside the step tables
            (repo.fake / "args.json").unlink(missing_ok=True)
            assert repo.review(step).returncode == 2, step
            assert not (repo.fake / "args.json").exists(), f"codex ran for step {step}"


def test_the_real_docs_give_each_step_only_its_step_table_rows():
    """catches: a review given rows of other tables in the real DESIGN or TESTING (the .gpt header's "| 40 | max_pixel_count |", §8's "| 21 empty files |"), or a number that only such rows match taken as a step (Claude skeptic, step 10)"""
    real = pathlib.Path(__file__).resolve().parents[2] / "docs"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp, docs={"docs/DESIGN.md": (real / "DESIGN.md").read_text(),
                               "docs/TESTING.md": (real / "TESTING.md").read_text()})
        for step in ["21", "24", "40"]:  # rows of the .gpt header's table and §8's, not steps (12 and 16 are steps now)
            assert repo.review(step).returncode == 2, step
        for step, words in [("8", "Export"), ("10", "GeoLife")]:
            assert repo.review(step).returncode == 0, step
            prompt = (repo.fake / "prompt.txt").read_text()
            rows = prompt.split("(DESIGN §12.2, or §12.4 for stage 2):\n")[1].split("\n\nTests this step")[0].splitlines()
            assert len(rows) == 2 and words in rows[0] and "uint32" not in prompt, (step, rows)


def test_reply_without_summary_does_not_use_up_a_round():
    """catches: a cut-short or off-format Codex reply counts as a round, so two bad replies end the reviews"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        (repo.fake / "no-summary").write_text("")
        result = repo.review()
        assert result.returncode == 1, result.returncode
        assert "SUMMARY" in result.stderr, result.stderr
        assert not (repo.root / ".review" / "step-0b" / "round-1.md").exists()
        assert "example finding" in repo.round_file("round-1.invalid.md"), "the reply is kept for reading"
        (repo.fake / "no-summary").unlink()
        assert repo.review().returncode == 0
        assert "This is round 2" not in (repo.fake / "prompt.txt").read_text()


def test_second_review_of_the_same_step_is_refused_while_one_runs():
    """catches: two reviews started together both pick round 1 and overwrite each other's diff, prompt and findings"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        (repo.fake / "slow").write_text("")
        first = repo.start_review()
        lock = repo.root / ".review" / "step-0b.lock"
        for _ in range(100):
            if lock.exists():
                break
            time.sleep(0.05)
        second = repo.review()
        out, err = first.communicate(timeout=30)
        assert second.returncode == 1, second.returncode
        assert "already running" in second.stderr, second.stderr
        assert first.returncode == 0, err
        assert "SUMMARY: high=0 medium=1 low=0" in repo.round_file("round-1.md")
        assert not lock.exists(), "the lock is removed when the review ends"


def test_lock_is_released_after_a_failed_run():
    """catches: a failed review leaves its lock behind, so every later review of the step is refused"""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repo(tmp)
        (repo.fake / "crash").write_text("")
        assert repo.review().returncode == 1
        assert not (repo.root / ".review" / "step-0b.lock").exists()
