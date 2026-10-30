# PROGRESS.md

The handoff file. Read it first. Update it at the start and end of every step.

## Now

| | |
|---|---|
| **Current step** | 3a: Build: external sort + write `.gpt` |
| **Status** | not started |
| **Next action** | Wait for the developer's "start step 3a". Before 3a: the DESIGN §9.4 World x wording (Open decisions). |
| **Blocked on** | Developer's go-ahead for step 3a |

Status values: `not started` → `in progress` → `waiting for review` → `approved`

## Step log (stage 1: T-Drive)

| Step | Name | Status | Date | Commit | Review |
|---|---|---|---|---|---|
| 0a | Project setup: build + tests | approved | 2026-10-28 | `0e0e3fb` | `docs/steps/step-0a.md` |
| 0b | Loop tools: verify, hooks, Codex review | approved | 2026-10-28 | `36419af` | `docs/steps/step-0b.md` |
| 1 | Map math | approved | 2026-10-29 | `c587160` | `docs/steps/step-1.md` |
| 2 | Importer | approved | 2026-10-29 | (this commit) | `docs/steps/step-2.md` |
| 3a | Build: external sort + write `.gpt` | not started | | | |
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
| DESIGN §8 import rules (columns from 1, blank lines, 65,536-byte limit, plain decimals, `--skip` per file, `--delim`) | Any time | Proposed in `docs/steps/step-2.md` Decisions, not applied. Code and tests already follow them |
| TESTING §7 wording for the 1 MB line, which the test makes instead of storing it in `bad_rows.txt` | Any time | Proposed in `docs/steps/step-2.md` Decisions, not applied |
| Store time per point? | Before stage 4 | Changes the `.gpt` format. DESIGN section 14 |
| Base map provider for the page | Step 6 | CARTO dark (used in the mockup) or OpenStreetMap |
| License for the release | Step 9 | Others can't legally use a package with no license. E.g. MIT, Apache-2.0 or GPL-3.0 |

## Known issues
- A fresh clone has no pre-commit hook until `make hooks` is run (installed in this checkout).
- Leak checks are not available in `make sanitize` on macOS arm64 (no LeakSanitizer). Overflows and use-after-free are caught.
