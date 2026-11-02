# Step 8: Export

## Summary

| | |
|---|---|
| **Built** | `GET /api/datasets/{id}/export.csv?bbox=w,s,e,n&limit=N`: the points in a box as CSV, streamed, at most 1,000,000 rows · an "Export CSV" link on the page under a drawn box |
| **Status** | approved (developer's go-ahead 2026-10-31) |
| **Date** | 2026-10-31 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Design
- **Same box, same squares as the count** (step 7): the points come out in file order (sorted by code). The total is counted first and sent as headers: `X-Total-Points` (in the box) and `X-Rows` (in this file).
- **A row is the middle of the point's world unit, 9 decimals** (about 0.1 mm), kept inside the box's degrees. Read back (an import, a box, a spreadsheet filter by the box) it is exactly that point, inside the box. A box edge lies inside the unit of the points on it, so a row moved onto the edge still reads back as its own unit. Where 9 decimals would round a value out of the box or into another unit (an edge given with more decimals; just west of 180, which would round to 180 = −180), it gets as many more decimals as it takes (never an exponent).
- **Streamed** in 64 KB chunks (HTTP/1.1 chunked encoding): memory stays the same for 10 rows or a million, and a cut-off download can be told from a finished one. An HTTP/1.0 client (no chunks) gets the rows as they are, ended by the closed connection.
- **A slow client is served; a stopped one is let go:** every write that goes through gives the client another 3 × `--timeout` seconds (30 s by default), so a script that reads steadily but slowly gets the whole file, and a client that stops reading for that long gives its connection slot back. Measured on this Mac: a write goes through only after the client has read about one socket buffer (0.5–0.7 MB), so with the default timeout a client keeps up at about 23 KB/s (a script writing each row to a database).
- **A row limit**, `limit` from 1 to 1,000,000 (the default and the most). The page asks for min(count, 1,000,000), and for a bigger box says it sends "the first 1,000,000 of N points, in file order" (the box's north-west part first). A box across the 180° line is two boxes: no link, and the panel says to draw one box on each side.
- **The file is named `{id}-export.csv`** (`Content-Disposition: attachment`), so a browser saves it instead of showing it.

```text
$ curl -s -D - 'http://127.0.0.1:PORT/api/datasets/tdrive/export.csv?bbox=116.55,40.03,116.65,40.10&limit=3'
HTTP/1.1 200 OK
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="tdrive-export.csv"
X-Total-Points: 239864
X-Rows: 3
Transfer-Encoding: chunked
X-Content-Type-Options: nosniff
Connection: close

lon,lat
116.550709982,40.099990002
116.550730015,40.099750019
116.550270016,40.098579971
```

## Files changed

| File | Change | Why |
|---|---|---|
| `src/server.c`, `src/server.h` | changed | the export route: limit, chunked CSV (plain for HTTP/1.0), rows kept in the box and in their unit, the per-write deadline |
| `src/area.c`, `src/area.h` | changed | a box keeps the degrees it was given |
| `src/geo.c`, `src/geo.h` | changed | `geo_lon`/`geo_lat` take a position in world units (`x + 0.5`: the middle of a unit) |
| `www/app.js`, `index.html`, `app.css` | changed | the Export link under a counted box |
| `tests/e2e/browser.py` | changed | downloads into a folder, waited for |
| `tests/e2e/test_export.py` | added | 14 tests |
| `tests/validate/step-8.sh` | added | DESIGN §12.2's check on T-Drive, with the page's Export link, and a slow reader |
| `docs/TESTING.md` | changed | test list |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| rows equal the box count and are inside the box | 25 boxes over 6,000 clustered points: the rows are exactly the points of the slow count, in file order, each read back as its point | edge points left out, rows outside the box, rows lost or repeated between chunks, a wrong total |
| every row reads back as its own point, even at the edges of the map | the world's corners and edges and 2,000 random points | rows rounded into the next unit, or past latitude 85.05112877980659 |
| rows stay inside the box read as plain numbers | box edges inside the corner points' units, given with 9 and with 17 digits | rows printed half a unit past an edge (a spreadsheet filter drops them) |
| a row in the last column does not round to 180 · rows near 0° never use exponents | a point on the world's last unit, boxes ending at 180 with edges just west of it; points around 0, 0 with 17-digit edges | a row clamped onto an edge and printed `180.000000000` (read back as −180); a row like `2.5e-05` |
| a client that reads steadily gets a long export | 120,000 rows (3.3 MB, well past the socket buffers) read at about 400 KB/s with `--timeout 1`: all rows, the final chunk, over 6 s | a deadline that doesn't move as the client reads (a slow script cut off) |
| the row limit is kept · the default limit is a million rows | limits 1 … 1,000,000, bad limits refused; 1,000,100 points → 1,000,000 rows, total 1,000,100 | a huge download, a limit of 0 or over 1,000,000, a total that counts only the rows sent |
| an HTTP/1.0 client gets the rows without chunks · HEAD has the counts and no rows | raw requests, read to the end | chunk sizes in a 1.0 client's CSV; HEAD sending the rows |
| a client that hangs up halfway · clients that stop reading give their slots back | 5 hang-ups; 70 clients asking for 5 MB and never reading, with `--timeout 1`, then an ordinary request within 10 s | the server dying (SIGPIPE) or every slot held by stuck exports |
| Chrome: the Export link of a drawn box downloads its rows | a box dragged with the mouse, the link clicked, the downloaded file = the slow count's rows; cleared by a switch | a link for another box or dataset, a link that doesn't download, a stale link |
| Chrome: the Export link says what it will send | 1 row · 1,000,100 points → "the first 1,000,000 of 1,000,100 points, in file order" and `limit=1000000` · a box across 180°: no link, a note | "1 rows", a link the server refuses, a file with one side of 180° only |
| `tests/validate/step-8.sh` | real T-Drive: the airport box's 239,864 rows = Python's points (file order, read back inside the box in units and as plain numbers); limit 1,000; the page's Export link clicked; a steady 400 KB/s reader with `--timeout 1` gets 64,000 rows | (validation) |

```text
make check       unit 33 passed 0 failed · e2e 117 passed 0 failed · ALL PASSED (build)
make sanitize    unit 33 passed 0 failed · e2e 117 passed 0 failed · ALL PASSED (build/san)
make check-data  as in step 4 (import, build, info + count, render on all of T-Drive)
make verify      VERIFY PASSED, 11 min 7 s (step-0a … 7 as before · step-8 5 ok)
--- tests/validate/step-8.sh
  ok  export.csv of bbox=116.55,40.03,116.65,40.10: 239,864 rows = the box count · header lon,lat · saved as build/validate/step-8.csv
  ok  every row is inside the box, and the rows are exactly Python's points of the box in file order
  ok  limit=1000 → 1,000 rows, the first 1,000 of the full export
  ok  page: a box drawn with the mouse, its Export link clicked: 73,779 rows downloaded = the box count = Python's points of the box · saved as build/validate/step-8-page.csv
  ok  a steady slow reader (about 400 KB/s, --timeout 1) got the whole export: 64,000 rows in 5.1 s
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 8` (gpt-6-astra, high reasoning effort). Files in `.review/step-8/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `server.c:384`: rows were the unit's north-west corner with 7 decimals; a row could read back as the neighbouring unit, and the top row printed 85.0511288 (past the map's edge) | Fixed: the middle of the unit with 9 decimals; every row is read back in the tests. Caught (E12) |
| 1 | Medium, `server.c:405`: HTTP/1.0 clients got chunked encoding | Fixed: plain rows ended by the closed connection; a raw HTTP/1.0 test. Caught (E11) |
| 1 | Low, `test_export.py:69`: the default 1,000,000 cap never exercised | Fixed: 1,000,100 points, with and without `limit`. Caught (E13) |
| 2 | Items 2 and 3 fixed; item 1 partly: a row clamped onto an edge just west of 180 printed as `180.000000000`, which reads back (as a point) as −180 | Fixed: a printed value must read back as its own unit by the point rule, else all 17 digits; the tests' read-back uses the point rule. Caught (E20) |

Left for the developer to decide: none. The last fix was not reviewed by Codex again (2-round limit); it is guarded by a test that a deliberate break showed failing.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copies, with its own servers on free ports, headless Chrome and timed raw-socket readers. Scripts: `scratchpad/reviews/step-8-claude-round1-scripts/`. It re-synced mid-review to take in the builder's HTTP/1.0 and row-format fixes.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium 1: the per-chunk deadline cut off steady slow readers (300 KB/s with `--timeout 1` was cut at 3.6 of 14.7 MB), and nothing capped a slow export | The deadline now moves with every write, with 3 × `--timeout` of pause allowed; measured: a write goes through only after the reader drains about one socket buffer, so the default lets about 23 KB/s through. No total cap, on purpose (Decisions). Caught (E14) |
| 1 | Medium 2: on the step's own box, 12 rows read as plain numbers were outside the box (a unit's middle half a unit past an edge) | Fixed: rows kept inside the box's degrees; `step-8.sh` checks every row as plain numbers with no slack, and a test puts edges inside the edge points' units. Caught (E16) |
| 1 | Low 3: "Export CSV (1 rows)" | Fixed. Caught (E17) |
| 1 | Low 4: "first 1,000,000 of N" is the north-west part, not a sample | The link says "in file order", and its tooltip says the north-west part comes first and to draw smaller boxes for the rest |
| 1 | Test gaps: no slow-but-reading client; the page link without the 1,000,000 cap; a link for a box across 180° | Fixed: the steady reader in `step-8.sh`; a Chrome test for the link texts (1 row, 1,000,100 points, a box across 180°). Caught (E14, E18, E19) |
| 1 | Already fixed when it ran: HTTP/1.0 chunks, the HEAD test that couldn't see a body, rows at ±85.0511288 | — |
| 1 | Checked and fine: rows = count in file order; a 1,000,000-row export in 0.28 s with valid chunks and 13 MB of server memory; ±180 and ±85.05 boxes; hang-ups and stopped readers; the link hidden while a new count loads and on a switch; keyboard access | — |
| 2 | Findings 2, 3, 4: fixed (the airport box: 0 rows outside, was 12; "1 row"; the link text and tooltip). Test gaps 2, 3: fixed | — |
| 2 | Finding 1 partly: steady readers are served (300 KB/s with `--timeout 1`: the whole 14.67 MB, was cut at 3.56), but there is no total cap, by decision; its cost: 64 clients each reading about 2.5 KB/s kept every slot, and an ordinary request waited 24 s. The `server.h` comment still said "6 × timeout to read the answer" | The decision stands (Decisions), its cost now written there; the comment fixed |
| 2 | Test gap 1 partly: a deadline that doesn't move was caught only by `make verify` | Fixed: `a_client_that_reads_steadily…` in `make check` (120,000 rows). Caught (E14) |
| 2 | Low N1: full-precision values near 0° in exponent form (`-2.5078654289245605e-05`) | Fixed: as many decimals as it takes, never an exponent; a test with points around 0, 0. Caught (E21) |

Left for the developer to decide: whether a total time limit on exports is wanted after all (Decisions).

## Proof the tests catch bugs

Each break in a fresh copy of the repo, then `make check` (or the named validation):

| # | Deliberate break | Test that failed |
|---|---|---|
| E1 | the row limit ignored | `the_row_limit_is_kept`, `head_of_an_export…`, `a_client_that_hangs_up…` |
| E2 | no final empty chunk | 4 tests (the client sees a cut-off download) |
| E3 | chunk sizes in decimal, not hex | 4 tests |
| E4 | no deadline for a client that stopped reading | `clients_that_stop_reading…` |
| E5 | HEAD sends the rows | `head_of_an_export…` (the raw answer, read to the end; `http.client` alone missed it at first) |
| E6 | rows with 6 decimals | `export_rows_equal…`, the Chrome download test |
| E7 | X-Total-Points = the rows sent | `the_row_limit_is_kept`, `head_of_an_export…` |
| E8 | limit=0 accepted | `the_row_limit_is_kept` |
| E9 | the Export link exports the view, not the drawn box | the Chrome download test |
| E10 | the Export link stays after the box is cleared | the Chrome download test |
| E11 | chunks sent to an HTTP/1.0 client | `an_http10_client…` |
| E12 | rows at the unit's corner with 7 decimals | `every_row_reads_back…`, `export_rows_equal…`, the Chrome download test |
| E13 | no default row limit | `the_default_limit_is_a_million_rows` |
| E14 | the deadline not moved as the client reads | `a_client_that_reads_steadily…` (and `step-8.sh`) |
| E16 | rows not kept inside the box's degrees | `rows_stay_inside_the_box…`, `a_row_in_the_last_column…` |
| E17 | "Export CSV (1 rows)" | `chrome_the_export_link_says_what_it_will_send` |
| E18 | the page's link asks for more than 1,000,000 rows | `chrome_the_export_link_says…` |
| E19 | a link for a box across 180° | `chrome_the_export_link_says…` |
| E20 | a value that 9 decimals round out of the box or into another unit kept | `a_row_in_the_last_column…`, `rows_stay_inside_the_box…`, `export_rows_equal…` |
| E21 | always 9 decimals, never more | the same three tests |

The code was restored exactly afterwards: yes (every break was made in a deleted scratch copy).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-8.sh` | 5 `ok` lines; `build/validate/step-8.csv` and `step-8-page.csv` | 5 `ok`: 239,864 rows = the count = Python's points, file order, inside the box as units and plain numbers; limit 1,000; the page's Export: 73,779 rows; a 400 KB/s reader got all 64,000 rows |
| open `build/validate/step-8.csv` in Numbers or Excel | 2 columns `lon`, `lat`; 239,864 rows, every one inside 116.55–116.65, 40.03–40.10 | not done by the agent (no Numbers by hand); checked with Python's csv reader and plain number filters |
| on http://127.0.0.1:8080/: Draw a box, then **Export CSV** | a `tdrive-export.csv` download with the box's count of rows | see Deploy |

## Deploy (after approval)

Step 7's deploy, done after its commit (`5db12b0`), with the new restart retry in place:

| Command | Smoke test | Rolled back? |
|---|---|---|
| `make deploy` (31 s, `make check` included) | green on the first try: the map page, 2 datasets, pid 84451 | no |
| `make status` | `current: releases/da206fe-…`, `previous: releases/e68e36f-…`, answering | — |
| `curl …/api/datasets/tdrive/count?bbox=116.55,40.03,116.65,40.10` on the service | `{"id":"tdrive","count":239864}` | — |

Step 8's own deploy follows this commit; its result is in step 9's file.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | export route, page link, tests, breaks, validation, this file |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **No total time limit on an export.** Tried in this step (6 × timeout plus a second per 1,000 rows) and dropped: it would cut off scripts that read slowly but steadily, its test needed over a minute (socket buffers hold 500–700 KB), and on a local server the risk it guards against comes only from the user's own programs. Measured by the skeptic: 64 clients each reading about 2.5 KB/s held every slot, and an ordinary request waited 24 s; a total limit would end that, at the price of cutting slow scripts. **For the developer to confirm.** A client that stops reading still loses its slot after 3 × `--timeout` seconds.
- **3 × `--timeout` of pause for an export's client** (other answers keep their 6 × timeout for the whole answer). Also tried and dropped, as measured to change nothing on macOS loopback: a 64 KB send buffer (377–680 KB still got out) and a progress check on the socket's send queue (`SO_NWRITE`; the queue doesn't move until the reader's window opens). A slower reader can be served by starting the server with a larger `--timeout`.
- **Rows are the middle of a unit, kept inside the box** (not the unit's north-west corner): exact when read back, and inside the box as plain numbers. Rows no longer repeat the source text digit for digit (`116.550709982` for `116.55071`); rounding to 5 decimals gives it back.
- **Proposed for DESIGN §9.2 (not applied without approval):** "export.csv rows: the middle of each point's world unit with 9 decimals, kept inside the bbox; at most 1,000,000 rows (limit), in file order; chunked for HTTP/1.1, plain for HTTP/1.0."

## Not verified
- Opening the CSV in Numbers or Excel by hand (checked with Python's csv reader and plain number filters).
- A client that reads so slowly it never stalls for 3 × `--timeout` seconds holds its slot until the export ends (no total limit, on purpose).
- Readers slower than about 23 KB/s with the default timeout (one socket buffer per 30 s) are let go; measured on this Mac's loopback only.
- Browsers other than Chrome.

## Next
- Step 9: benchmarks, the README, `make release-test` and `make release` (a local package and tag only), the stage 1 report.
