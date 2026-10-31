# Step 5a: Web server

## Summary

| | |
|---|---|
| **Built** | `server` (HTTP/1.1, one thread per connection, at most 64 at once) and `gpstiles serve [--host 127.0.0.1] [--port 8080] FILE.gpt...`: dataset info as JSON and heat-map tiles as PNG, for up to 32 datasets at once |
| **Status** | approved (developer's go-ahead 2026-10-31) |
| **Date** | 2026-10-31 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Design
- **One small server, no library.** Each connection gets a thread; a 65th waits until one finishes, so a burst of tile requests can't use up the machine. Each connection carries one request (`Connection: close`). The whole request (at most 8 KB of request line + headers) must arrive within 10 seconds (`--timeout`), and the whole answer be read within 60 more: one deadline each, so a client sending a byte now and then can't hold a slot.
- **Every request checked before use** (RFC 9112): `METHOD SP /target SP HTTP/1.0|HTTP/1.1`; header lines `Name: value` with no space before the colon; exactly one `Host` for HTTP/1.1; only `GET` and `HEAD`. Ids, zooms and tile numbers are parsed strictly (digits only). A NUL byte → 400, a request line over 8 KB → 414, headers over 8 KB → 431, a slow sender → 408, a request cut short → 400. Wrong things get a one-line text answer with the right status, and the next request works as before.
- **Read-only and local.** It listens on 127.0.0.1 unless `--host` says otherwise. It answers only requests addressed to `localhost` or an IP address: a web page from another site that points its own name at this machine (DNS rebinding) sends that name and gets 403, whatever address the server listens on. No CORS headers, so other sites' pages can't read the answers either.
- **A dataset's id is its file name** without `.gpt` (`data/build/tdrive.gpt` → `tdrive`): 1–32 of `a-z 0-9 - _`, no two the same, at most 32 files. Each file is memory-mapped (step 3b), so serving 32 datasets costs little RAM up front.
- **The first line on stdout names the address**, `gpstiles serve: http://127.0.0.1:PORT/`; with `--port 0` the system picks a free port, so tests can run side by side.

| Request | Answer |
|---|---|
| `GET /api/datasets` | 200 `application/json`: `{"datasets":[{"id","points","bounds","view","max_zoom","max_pixel"}, ...]}` in command-line order. Boxes are `[west,south,east,north]` in degrees, `null` for an empty dataset |
| `GET /api/datasets/{id}` | 200 JSON: that one dataset |
| `GET /tiles/{id}/{z}/{x}/{y}.png` | 200 `image/png` (step 4's picture), header `X-Points`: the points in the tile |
| unknown path or id · tile outside the world | 404, a short text |
| non-numeric zoom, x or y | 400 |
| `HEAD` of any of these | the same status and headers, no body |
| any other method | 405 with `Allow: GET, HEAD` |

## Files changed

| File | Change | Why |
|---|---|---|
| `src/server.h`, `src/server.c` | added | routing (pure: `server_route`), responses, JSON, connections, the listener |
| `src/main.c` | changed | `serve` command: `--host`, `--port`, `--timeout`, dataset ids from file names, opening every file before listening |
| `tests/e2e/test_server.py` | added | 8 tests, real HTTP |
| `tests/validate/step-5a.sh`, `lib.sh` | added / changed | the DESIGN §12.2 check · `tdrive_sample_gpt`: the first 500 T-Drive files as a second dataset |
| `docs/TESTING.md` | changed | test list |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_each_endpoint_answers_with_its_status_type_and_body` | 2 datasets; `/api/datasets` and `/api/datasets/{id}` against `gpt_rules.py` (counts, bounds and view in degrees, densest pixels), in command-line order; each dataset's busiest zoom-6 tile decoded and compared pixel by pixel with `tile_rules.py`; `X-Points` | a dataset listed with another's numbers, a tile drawn from the wrong dataset or tile, a wrong content type |
| `test_bad_requests_get_an_error_and_the_next_request_still_works` | 34 bad requests (unknown paths and ids, tiles outside the world, non-numeric parts, POST/DELETE, 3 foreign Hosts, a space before a colon, no or two Hosts, a header line without a colon, 10 KB request line and headers, bad request lines and versions, NUL bytes) → the right status, a one-line text body whose length is `Content-Length`, and the next request still works · a request cut short → 400 · hang-ups mid-request | a crash, hang or wrong answer on bad input, DNS rebinding |
| `test_other_ways_to_ask_get_the_same_answer` | Host as `localhost`, with a port, upper case, an IP, `[::1]`, a trailing space → the same JSON · `?x=1` and `?v=1` ignored · HEAD = GET's headers without the body, also on the raw wire and when refused · PUT → 405 `Allow: GET, HEAD` | a browser at http://localhost refused, `curl -I` refused, a cache-busting query string breaking a route |
| `test_50_requests_at_once_all_get_the_right_answer` | 50 tile requests at once while an idle connection is open: all right (`X-Points` = Python), all within 5 s | a data race, dropped requests, connections served one at a time |
| `test_a_slow_client_cannot_hold_a_connection_slot` | `--timeout 1`; 70 clients each dripping a byte every 0.3 s (more than the 64 slots): a normal request is answered within 4 s, and the drippers get 408 | a timeout that restarts with every byte (64 slow clients would stop the map) |
| `test_the_server_does_not_grow_with_each_request` | the server's memory (RSS) grows by less than 16 MB over 2,000 tiles · then macOS's `leaks` finds 0 leaks after JSON, error and HEAD requests (skipped under the sanitizers) | a buffer leaked per request, big or small |
| `test_many_requests_in_a_row_are_all_answered` | 150 requests one after another | a connection slot not given back (the server would stop after 64) |
| `test_serve_refuses_bad_arguments_and_files` | 14 bad starts: missing files, bad `--port`/`--host`/`--timeout`, ids that break URLs, two files with the same id, a broken `.gpt`, 33 files, a busy port → exit 1 or 2, one line | a bad dataset served, a crash at start |

```text
make check       unit 31 passed 0 failed · e2e 91 passed 0 failed · ALL PASSED (build)
make sanitize    unit 31 passed 0 failed · e2e 91 passed 0 failed · ALL PASSED (build/san)
make check-data  as in step 4 (import, build, info, count, render all = Python / awk / DESIGN §13)
make verify      VERIFY PASSED, 4 min 15 s (step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 7 ok · 3b 3 ok · 4 7 ok · 5a 11 ok)
--- tests/validate/step-5a.sh
  ok  serving both datasets on http://127.0.0.1:54016
  ok  /api/datasets: tdrive 10,064,891 points (DESIGN §13) · tdrive-sample 543,401 points (= awk over the same 500 files)
  ok  /tiles/tdrive/11/1686/776.png: 1,849,140 points and all 65,536 pixels = Python's from tdrive's own points
  ok  /tiles/tdrive-sample/11/1686/776.png: 97,094 points and all 65,536 pixels = Python's from tdrive-sample's own points
  ok  /tiles/nope/11/1686/776.png → 404 404 unknown dataset · the next request still works
  ok  /api/datasets/nope → 404 404 unknown dataset · the next request still works
  ok  /tiles/tdrive/25/0/0.png → 404 404 no such tile · the next request still works
  ok  /tiles/tdrive/x/1/2.png → 400 400 bad tile address: zoom, x and y must be whole numbers · the next request still works
  ok  /no/such/page → 404 404 not found · the next request still works
  ok  /tiles/tdrive/11/1686 → 404 404 not found · the next request still works
  ok  server stopped
VERIFY PASSED
make verify  162.05s user 38.64s system 78% cpu 4:15.15 total
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 5a` (gpt-6-astra, high reasoning effort). Files in `.review/step-5a/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `src/server.c:340`: the read timeout restarted with every byte (and the drain's "1 second" with every read), so slow clients could hold all 64 slots for hours | Fixed: one deadline for the whole request (`--timeout`, default 10 s), one for draining (1 s), one for writing the answer (60 s), with `poll`. Test `test_a_slow_client_cannot_hold_a_connection_slot`. Caught (S9) |
| 1 | Low, `src/server.c:274`: `HTTP/1.`, `HTTP/1.garbage` and trailing tokens were accepted | Fixed: exactly `HTTP/1.0` or `HTTP/1.1` at the line's end. Caught (S11) |
| 1 | Low, `src/server.c:258`: other loopback addresses (`127.0.0.2`) failed their own Host check | Fixed: any IP address is accepted as Host (rebinding always uses a name) |
| 1 | Low, `tests/validate/step-5a.sh:56`: the real-data check didn't prove each tile came from its own dataset | Fixed: each dataset's tile is compared with Python's count and all 65,536 pixel colors from that dataset's own points, and the two tiles must differ |
| 2 | The four round-1 findings: "Fixed" | — |
| 2 | Medium, `src/server.c:155`: sockets were still blocking, so one `write()` larger than the free send buffer could block past the 60 s deadline if the client stopped reading | Fixed: accepted sockets are non-blocking (`O_NONBLOCK`), so every write waits in `poll` with the deadline. No 5a answer is larger than the 128 KB send buffer (the biggest real tile is 58 KB), so no 5a request can show it; step 8's export test (a client that stops reading a multi-MB CSV) covers it |

Left for the developer to decide: none. The round-2 fix was not reviewed by Codex again (2-round limit); the Claude skeptic's round 2 had asked for the same change.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, running servers only on 127.0.0.1 `--port 0`. It found the request path sound under the sanitizers (oversized requests, NUL bytes, router edge cases, empty datasets, start-up checks) and the threads sharing nothing but the locked slot counter.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium F1: same as Codex's medium (proven with 64 dripping sockets: a normal request timed out) | Fixed as above. Caught (S9) |
| 1 | Medium F2, `tests/e2e/test_server.py` (`Server`): a server that starts wrong made the tests hang forever or leave servers running | Fixed: the address line is read with a 10 s deadline, and the server is killed on any failure |
| 1 | Low F3: the Host check was skipped for `--host 0.0.0.0` (also answering on 127.0.0.1) | Fixed: the check always runs |
| 1 | Low F4: HEAD got 405 (RFC 9110 says general-purpose servers support it; `curl -I` uses it) | Fixed: HEAD = GET without the body, `Allow: GET, HEAD`. Caught (S12) |
| 1 | Low F5: `Host : evil` (space before the colon) skipped the Host check; HTTP/1.1 without Host was served; a trailing space was refused | Fixed: such lines → 400, Host required for 1.1, trailing spaces trimmed. Caught (S13, S14) |
| 1 | Low F6: a request cut short (half-close, or LF-only lines) got no answer | Fixed: 400 "request cut short" |
| 1 | Low F7 (latent): an error message over ~150 bytes would have sent stack bytes | Fixed: the length is capped at the buffer |
| 1 | Test gaps G1–G7: connections served one at a time, `localhost` refused, no timeout test, query strings, a memory leak, error bodies unchecked, tiles from the wrong dataset in the validation | All closed by the tests above. Caught (S18, S17, S9, S15, S16) |
| 2 | F1–F7 and G1–G7: all fixed (G5 partly: see the next row), each re-run with its round-1 reproduction or mutant | — |
| 2 | Test gap G5 (rest): a small leak (a JSON answer, ~400 bytes) doesn't show in the server's size | Fixed: the memory test also runs macOS's `leaks` on the server after JSON, error and HEAD requests and expects "0 leaks". Caught (S20) |
| 2 | Low N1: the write deadline didn't limit one blocking `write()` | Fixed with Codex round 2's medium (non-blocking sockets) |
| 2 | Low N2: a HEAD request refused for a bad header got a body | Fixed: "no body" is decided before any check. Test: HEAD on the raw wire (200, 404, 400) ends after its headers. Caught (S19) |

Left for the developer to decide: none.

## Proof the tests catch bugs

Each break in a fresh scratch copy, `make check`:

| # | Deliberate break | Tests that failed |
|---|---|---|
| S1 | NUL bytes not refused | `test_bad_requests…` |
| S2 | no lingering close | `test_bad_requests…` (the 414 answer lost to a reset) |
| S3 | a foreign Host accepted | `test_bad_requests…` |
| S4 | tile y not checked against the zoom | `test_bad_requests…` |
| S5 | a connection slot never given back | `test_many_requests_in_a_row…`, `test_a_slow_client…`, `test_the_server_does_not_grow…`, `test_bad_requests…` |
| S6 | 414 and 431 swapped | `test_bad_requests…` |
| S7 | any dataset id accepted | `test_serve_refuses_bad_arguments_and_files` |
| S8 | two datasets with the same id accepted | `test_serve_refuses_bad_arguments_and_files` |
| S9 | the timeout restarts with every byte | `test_a_slow_client_cannot_hold_a_connection_slot` |
| S10 | every Host name accepted | `test_bad_requests…` |
| S11 | any `HTTP/1.x` accepted | `test_bad_requests…` |
| S12 | HEAD refused | `test_other_ways_to_ask_get_the_same_answer` |
| S13 | HTTP/1.1 without Host accepted | `test_bad_requests…` |
| S14 | a space before a header's colon accepted | `test_bad_requests…` (the HTTP/1.0 case) |
| S15 | the query string kept in the path | `test_other_ways_to_ask_get_the_same_answer` |
| S16 | every tile's PNG leaked | `test_the_server_does_not_grow_with_each_request` |
| S17 | `localhost` refused | `test_other_ways_to_ask_get_the_same_answer` |
| S18 | connections served one at a time | `test_50_requests_at_once…`, `test_a_slow_client…` |
| S19 | a HEAD answer sends its body | `test_other_ways_to_ask_get_the_same_answer` (HEAD on the raw wire) |
| S20 | every JSON answer leaked | `test_the_server_does_not_grow_with_each_request` (macOS `leaks`) |

The code was restored exactly afterwards: yes (every break was in a deleted scratch copy).

Not tested by a deliberate break: SIGPIPE being ignored. No 5a request makes the server write to a client that has gone; step 8's export test does (a client hanging up halfway through a download).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `build/gpstiles serve data/build/tdrive.gpt data/build/tdrive-sample.gpt` (keep it running; then in a second terminal:) | `gpstiles serve: http://127.0.0.1:8080/` | as expected |
| `curl -s http://127.0.0.1:8080/api/datasets` | both datasets with their points: 10,064,891 and 543,401 | as expected |
| open http://127.0.0.1:8080/tiles/tdrive/11/1686/776.png in a browser | central Beijing's roads in heat colors | as expected |
| `curl -si http://127.0.0.1:8080/tiles/nope/0/0/0.png` | `404` and `404 unknown dataset` | as expected |
| `curl -s -H 'Host: evil.example' http://127.0.0.1:8080/api/datasets` | `403 this server only answers requests for localhost or an IP address` | as expected |
| `bash tests/validate/step-5a.sh` | 11 `ok` lines | 11 `ok` (output above) |

`data/build/tdrive-sample.gpt` was made for this step: `build/gpstiles import --lon-col 3 --lat-col 4 -o data/build/tdrive-sample.pts $(ls data/raw/tdrive_txt/*.txt | sort | head -500)`, then `build/gpstiles build -o data/build/tdrive-sample.gpt data/build/tdrive-sample.pts`.

## Deploy (from step 5b, after approval)

| Command | Smoke test | Rolled back? |
|---|---|---|
| none (deploy starts at step 5b) | | |

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | code, tests, breaks, validation, this file |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own scratch copy) | adversarial review |

## Decisions
- **A thread per connection, one request each** (`Connection: close`). Simple and isolated: a slow tile doesn't hold up others. Rejected: an event loop (more code for the same local use), keep-alive (idle connections would hold threads; localhost connections are cheap).
- **Deadlines, not per-read timeouts, on non-blocking sockets:** 10 s for the request (`--timeout`, added so tests can use 1 s), 6 × that (60 s) to send the answer, 1 s to drain unread input. Every read and write waits in `poll` with its deadline.
- **Host names refused, IP addresses accepted:** DNS rebinding needs a name, so any IP address (127.0.0.2, a LAN address with `--host 0.0.0.0`) and `localhost` are safe; every other name gets 403. Rejected: listing allowed names (a server can't know all its addresses).
- **HEAD supported** (RFC 9110), so `curl -I` and link checkers work.
- **JSON shape** (proposed for DESIGN §9.2, not applied): `{"datasets":[…]}`; each dataset `{"id","points","bounds","view","max_zoom","max_pixel"}`, boxes `[west,south,east,north]` in degrees or `null`. `max_pixel` (25 numbers) lets the page show the color key (step 6).
- **No request log:** the server prints only its address and start-up errors, so a service running for months doesn't fill the disk (step 5b).
- **`make check` now takes about 16 s** (the server tests wait on real timeouts and 2,000 requests), above TESTING §12.2's 10 s. Proposed (not applied): raise the budget to 30 s. The 6-second write-deadline test goes into step 8's validation script instead of `make check` for the same reason.

## Not verified
- More than 64 slow clients from other machines (only possible with `--host` other than 127.0.0.1); the deadlines bound each one.
- IPv6 (`--host` takes IPv4 only).
- Memory leaks: checked with macOS's `leaks` in the plain build only (LeakSanitizer isn't available on macOS arm64, and `leaks` can't read an AddressSanitizer process).
- A client that stops reading a large answer: no 5a answer is large enough to block (see Codex round 2); tested in step 8.

## Next
- Step 5b: run this server as a service on this Mac (launchd), with a smoke test and rollback.
