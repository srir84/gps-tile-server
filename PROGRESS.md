# PROGRESS.md

The handoff file. Read it first. Update it at the start and end of every step.

## Now

| | |
|---|---|
| **Current step** | 3b: Read `.gpt`: tilefile, info, count |
| **Status** | in progress |
| **Next action** | Build step 3b (DESIGN §12.2), verify, Codex + Claude skeptic reviews, then commit `step 3b: read .gpt`. |
| **Blocked on** | nothing |

Approval: on 2026-10-31 the developer set the goal "complete each step … do not stop until the full project is completed", with Codex (gpt-6-astra) and a Claude Opus skeptic reviewing every step. Each step is committed after both reviews and a green `make verify`. Deploy is local only (this Mac); nothing is published.

Status values: `not started` → `in progress` → `waiting for review` → `approved`

## Step log (stage 1: T-Drive)

| Step | Name | Status | Date | Commit | Review |
|---|---|---|---|---|---|
| 0a | Project setup: build + tests | approved | 2026-10-28 | `0e0e3fb` | `docs/steps/step-0a.md` |
| 0b | Loop tools: verify, hooks, Codex review | approved | 2026-10-28 | `36419af` | `docs/steps/step-0b.md` |
| 1 | Map math | approved | 2026-10-29 | `c587160` | `docs/steps/step-1.md` |
| 2 | Importer | approved | 2026-10-29 | `0777186` | `docs/steps/step-2.md` |
| 3a | Build: external sort + write `.gpt` | approved | 2026-10-31 | | `docs/steps/step-3a.md` |
| 3b | Read `.gpt`: tilefile, info, count | not started | | | |
| 4 | Tile drawing | not started | | | |
| 5a | Web server | not started | | | |
| 5b | Local deploy (service, smoke test, rollback) | not started | | | |
| 6 | Map page | not started | | | |
| 7 | Area count + API | not started | | | |
| 8 | Export | not started | | | |
| 9 | Stage 1 report + release | not started | | | |

## Done before step 0 (planning)

| Item | Where |
|---|---|
| Design doc with diagrams | `docs/DESIGN.md` |
| Agent rules | `AGENTS.md`, `CLAUDE.md` |
| Step review template | `docs/steps/TEMPLATE.md` |
| T-Drive data downloaded | `data/raw/tdrive/`, `data/raw/tdrive_txt/` |
| Project plan and datasets | `../PROJECT_IDEAS.md` sections 8–10 |
| Mockup of the finished page | https://claude.ai/artifact/6eS7M1H57qtoZ7oYseCbST |

## Last verified

| Date | What | Command | Result |
|---|---|---|---|
| 2026-10-31 | Step 3a after both Claude skeptic rounds: `make verify` | `make verify` | unit 25/0 · e2e 71/0 under check and sanitize · check-data as before · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 7 ok (256 runs at `--mem 1M`: 3 MiB peak) · VERIFY PASSED (2 min 57 s) |
| 2026-10-30 | Step 3a: `make verify` from clean | `make clean && make verify` | unit 23/0 · e2e 65/0 under check and sanitize · check-data: import as step 2, build 1 run and 77 runs identical, `.gpt` = Python byte for byte · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 5 ok · VERIFY PASSED (2 min 31 s) |
| 2026-10-29 | Step 2: `make verify` from clean | `make clean && make verify` | unit 17/0 · e2e 58/0 under check and sanitize · check-data: counts = DESIGN §13 = awk, all 10,064,891 codes = Python · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · VERIFY PASSED (1 min 38 s) |
| 2026-10-28 | Step 1: `make verify` from clean | `make clean && make verify` | unit 10/0 · e2e 43/0 under check and sanitize · step-0a 2 ok · step-0b 7 ok · step-1 2 ok · VERIFY PASSED · Codex round 2: high=0 medium=0 low=0 |
| 2026-10-28 | Step 0b: `make verify` from clean | `make clean && make verify` | unit 1/0 · e2e 33/0 under check and sanitize · step-0a.sh 2 ok · step-0b.sh 7 ok · VERIFY PASSED · Codex round 2: high=0 medium=0 low=0 |
| 2026-10-28 | Step 0a: `make check` + `make sanitize` from clean | `make clean && make check && make sanitize` | unit 1/0 · e2e 18/0 · both exit 0 · sanitizers present (`nm`) |
| 2026-10-28 | T-Drive row counts (independent of our code) | `awk` over `data/raw/tdrive_txt/*.txt` | 10,088,351 rows · 23,357 at (0,0) · 103 out of range · 0 malformed |
| 2026-10-28 | Design diagrams render | `bake_mermaid.py docs/DESIGN.md` | 9 mermaid baked, 0 failed · 8 images in `docs/images/`, all linked files exist |

## Open decisions

| Decision | Needed by | Notes |
|---|---|---|
| DESIGN §9.4 World x wording | Before step 3a | Says "then `mod 2^32`", which taken literally is the step 1 round-1 bug. Proposed wording in `docs/steps/step-1.md` Decisions. Code already follows the proposal |
| DESIGN §9.3 `.gpt` header layout (byte offsets, field order, pixel = top 2(z+8) bits, view box rule, 0 points) | Before step 3b | Proposed in `docs/steps/step-3a.md` Decisions, not applied. Code and tests follow it |
| DESIGN §8 import rules (columns from 1, blank lines, 65,536-byte limit, plain decimals, `--skip` per file, `--delim`) | Any time | Proposed in `docs/steps/step-2.md` Decisions, not applied. Code and tests already follow them |
| TESTING §7 wording for the 1 MB line, which the test makes instead of storing it in `bad_rows.txt` | Any time | Proposed in `docs/steps/step-2.md` Decisions, not applied |
| Store time per point? | Before stage 4 | Changes the `.gpt` format. DESIGN section 14 |
| Base map provider for the page | Step 6 | CARTO dark (used in the mockup) or OpenStreetMap |
| License for the release | Step 9 | Others can't legally use a package with no license. E.g. MIT, Apache-2.0 or GPL-3.0 |

## Known issues
- A fresh clone has no pre-commit hook until `make hooks` is run (installed in this checkout).
- Leak checks are not available in `make sanitize` on macOS arm64 (no LeakSanitizer). Overflows and use-after-free are caught.
- A step's commit hash is written into this file after the commit, so it goes in with the next step's commit.
