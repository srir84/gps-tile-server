# PROGRESS.md

The handoff file. Read it first. Update it at the start and end of every step.

## Now

| | |
|---|---|
| **Current step** | 9: Stage 1 report |
| **Status** | in progress |
| **Next action** | `make deploy` of the step-8 commit, then step 9 (bench, README, `make release-test`, the stage 1 report), verify, reviews, commit, deploy, then `make release VERSION=0.1.0` (local only). |
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
| 3a | Build: external sort + write `.gpt` | approved | 2026-10-31 | `c974041` | `docs/steps/step-3a.md` |
| 3b | Read `.gpt`: tilefile, info, count | approved | 2026-10-31 | `98e0f88` | `docs/steps/step-3b.md` |
| 4 | Tile drawing | approved | 2026-10-31 | `1114779` | `docs/steps/step-4.md` |
| 5a | Web server | approved | 2026-10-31 | `4fba06c` | `docs/steps/step-5a.md` |
| 5b | Local deploy (service, smoke test, rollback) | approved | 2026-10-31 | `e46af4d` | `docs/steps/step-5b.md` |
| 6 | Map page | approved | 2026-10-31 | `e68e36f` | `docs/steps/step-6.md` |
| 7 | Area count + API | approved | 2026-10-31 | `da206fe` | `docs/steps/step-7.md` |
| 8 | Export | approved | 2026-10-31 | | `docs/steps/step-8.md` |
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
| 2026-10-31 | Step 8 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 33/0 · e2e 117/0 under check and sanitize · step-8 5 ok (real T-Drive: rows = Python's points, the page's Export, a steady slow reader) · VERIFY PASSED (11 min 7 s) |
| 2026-10-31 | Deploy of step 7 (`da206fe`) | `make deploy`, `make status` | smoke test green on the first try (pid 84451) · the live count API: 239,864 for the airport box |
| 2026-10-31 | Step 7 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 33/0 · e2e 103/0 under check and sanitize · step-7 4 ok (real T-Drive, the page's hover and box = Python) · step-5b 21 deploy scenarios · VERIFY PASSED (8 min 5 s) |
| 2026-10-31 | Deploy of step 6 (`e68e36f`) | `make deploy` ×2, then traced | 2 tries: launchd error 5 on restart, rolled back to 5b automatically · 3rd: smoke test green with the map page, pid 80452 · footprint 3 MB |
| 2026-10-31 | Step 6 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 96/0 under check and sanitize · step-6 4 ok (headless Chrome, real T-Drive, real base map) · VERIFY PASSED (6 min 57 s) |
| 2026-10-31 | Deploy of step 5b (`e46af4d`) | `make deploy`, `make status` | smoke test green (2 datasets, pid 55018 on 127.0.0.1:8080) · footprint 3 MB |
| 2026-10-31 | Step 5b after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 91/0 under check and sanitize · step-5b 17 ok (`make deploy-test`: 16 scenarios, nothing left) · VERIFY PASSED (6 min 4 s) |
| 2026-10-31 | Step 5a after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 91/0 under check and sanitize · check-data as step 4 · step-5a 11 ok (each dataset's tile = Python's from its own points) · VERIFY PASSED (4 min 15 s) |
| 2026-10-31 | Step 4 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 83/0 under check and sanitize · check-data: render 11/1686/776 = Python for all 65,536 pixels · step-4 7 ok (screenshot beside OpenStreetMap) · VERIFY PASSED (3 min 18 s) |
| 2026-10-31 | Step 3b after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 28/0 · e2e 78/0 under check and sanitize · check-data: info = DESIGN §13 and the Python header, count 10/843/388 = 2,229,964 = slow count = its 4 children · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 7 ok · 3b 3 ok · VERIFY PASSED (3 min 5 s) |
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
| ~~DESIGN §9.4, §9.3, §8 and TESTING §7 wording~~ | — | Applied in step 3b (see `docs/steps/step-3b.md` Decisions) |
| Store time per point? | Before stage 4 | Changes the `.gpt` format. DESIGN section 14 |
| Base map provider for the page | Developer to confirm | Step 6 uses OpenStreetMap's standard tiles, darkened by CSS (CARTO's dark tiles need an account). A one-line change in `www/app.js` plus the CSP |
| Box rule wording (DESIGN §9.2) | Developer to confirm | Longitude 180 as a box edge = the world's last unit; bbox at most 127 characters, each number at most 63. See `docs/steps/step-7.md` Decisions |
| A total time limit on exports | Developer to confirm | None in step 8, on purpose: a client that keeps reading is served; one that pauses 3 × timeout is let go. See `docs/steps/step-8.md` Decisions |
| Test time budgets (TESTING §2) | Developer to confirm | Proposed: `make check` under 30 s, `make sanitize` under 60 s (now about 17 s and 23 s; the e2e budget of 5 s was passed in step 5a) |
| License for the release | Step 9 | Others can't legally use a package with no license. E.g. MIT, Apache-2.0 or GPL-3.0 |

## Known issues
- A fresh clone has no pre-commit hook until `make hooks` is run (installed in this checkout).
- Leak checks are not available in `make sanitize` on macOS arm64 (no LeakSanitizer). Overflows and use-after-free are caught.
- A step's commit hash is written into this file after the commit, so it goes in with the next step's commit.
