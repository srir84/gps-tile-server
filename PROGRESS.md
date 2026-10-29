# PROGRESS.md

The handoff file. Read it first. Update it at the start and end of every step.

## Now

| | |
|---|---|
| **Current step** | 0b: Loop tools (verify, hooks, Codex review) |
| **Status** | approved |
| **Next action** | Wait for the developer to say "start step 1". Then build step 1 (map math) as DESIGN section 12.2 describes. |
| **Blocked on** | Developer's go-ahead for step 1 |

Status values: `not started` → `in progress` → `waiting for review` → `approved`

## Step log (stage 1: T-Drive)

| Step | Name | Status | Date | Commit | Review |
|---|---|---|---|---|---|
| 0a | Project setup: build + tests | approved | 2026-10-28 | `0e0e3fb` | `docs/steps/step-0a.md` |
| 0b | Loop tools: verify, hooks, Codex review | approved | 2026-10-28 | | `docs/steps/step-0b.md` |
| 1 | Map math | not started | | | |
| 2 | Importer | not started | | | |
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
| 2026-10-28 | Step 0b: `make verify` from clean | `make clean && make verify` | unit 1/0 · e2e 33/0 under check and sanitize · step-0a.sh 2 ok · step-0b.sh 7 ok · VERIFY PASSED · Codex round 2: high=0 medium=0 low=0 |
| 2026-10-28 | Step 0a: `make check` + `make sanitize` from clean | `make clean && make check && make sanitize` | unit 1/0 · e2e 18/0 · both exit 0 · sanitizers present (`nm`) |
| 2026-10-28 | T-Drive row counts (independent of our code) | `awk` over `data/raw/tdrive_txt/*.txt` | 10,088,351 rows · 23,357 at (0,0) · 103 out of range · 0 malformed |
| 2026-10-28 | Design diagrams render | `bake_mermaid.py docs/DESIGN.md` | 9 mermaid baked, 0 failed · 8 images in `docs/images/`, all linked files exist |

## Open decisions

| Decision | Needed by | Notes |
|---|---|---|
| Store time per point? | Before stage 4 | Changes the `.gpt` format. DESIGN section 14 |
| Base map provider for the page | Step 6 | CARTO dark (used in the mockup) or OpenStreetMap |
| License for the release | Step 9 | Others can't legally use a package with no license. E.g. MIT, Apache-2.0 or GPL-3.0 |

## Known issues
- A fresh clone has no pre-commit hook until `make hooks` is run (installed in this checkout).
- Leak checks are not available in `make sanitize` on macOS arm64 (no LeakSanitizer). Overflows and use-after-free are caught.
