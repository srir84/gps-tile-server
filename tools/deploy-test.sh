#!/bin/bash
# deploy-test.sh: `make deploy-test` (TESTING.md §12.4, §12.6): the whole deploy cycle in build/deploy-test/ with a
# test label of its own (local.gpstiles.test-<checksum of this checkout>) on a free port, never touching the
# real service. Covers: a failed first install leaves nothing; a good release goes live; a release name is
# never reused; a release that works alone but fails as the service is rolled back; programs that exit,
# serve bad tiles or hang are refused before the service is touched; a bad datasets.conf and another
# program on the port are refused; `rollback` swaps releases; launchd restarts a killed server; `status`
# answers quickly; everything is removed afterwards. On failure the service log is kept in build/.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
work=$ROOT/build/deploy-test

export GPSTILES_HOME=$work/home
export GPSTILES_AGENTS=$work/agents
export GPSTILES_LABEL=local.gpstiles.test-$(printf '%s' "$ROOT" | cksum | cut -d' ' -f1)
export GPSTILES_THROTTLE=1
GPSTILES_PORT=$(python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])') ||
    exit 1
export GPSTILES_PORT
DOMAIN=gui/$(id -u)
lock=$ROOT/build/deploy-test.lock
plain=

fail() {
    echo "deploy-test FAILED: $*"
    cp "$GPSTILES_HOME/logs/serve.log" "$ROOT/build/deploy-test-failed.log" 2> /dev/null &&
        echo "  (the service log is kept in build/deploy-test-failed.log)"
    exit 1
}

ok() {
    echo "  ok  $*"
}

cleanup() {
    [ -n "$plain" ] && kill "$plain" 2> /dev/null
    launchctl bootout "$DOMAIN/$GPSTILES_LABEL" 2> /dev/null
    rm -rf "$work"
}

mkdir -p "$ROOT/build" || exit 1
mkdir "$lock" 2> /dev/null || { echo "deploy-test: another deploy-test is running here (or remove $lock)"; exit 1; }
trap 'cleanup; rmdir "$lock"' EXIT
cleanup
mkdir -p "$GPSTILES_HOME" "$work/bin" || exit 1

current() {
    readlink "$GPSTILES_HOME/current" 2> /dev/null
}

deploy() { # release name, program
    GPSTILES_RELEASE=$1 GPSTILES_BINARY=$2 tools/deploy.sh deploy > "$work/deploy.out" 2>&1
}

# A tiny dataset (3 points) and the test programs.
python3 -I -c 'import struct, sys; sys.stdout.buffer.write(struct.pack("<3Q", 1, 2**40, 2**63))' > "$work/tiny.pts" &&
    build/gpstiles build -o "$work/tiny.gpt" "$work/tiny.pts" > /dev/null || fail "can't build the test dataset"
echo "$work/tiny.gpt" > "$GPSTILES_HOME/datasets.conf"
printf '#!/bin/sh\nexit 1\n' > "$work/bin/exits"
printf '#!/bin/sh\n# Works when run by hand, fails when launchd starts it (in /).\n[ "$(pwd)" = / ] && exit 1\nexec %q "$@"\n' \
    "$ROOT/build/gpstiles" > "$work/bin/fails-as-service"
cat > "$work/bin/bad-tiles" <<'PY'
#!/usr/bin/env python3
# Answers like gpstiles serve, wrong in one way, named by how it is called: bad-tiles (tiles are text),
# corrupt-png (a PNG whose image data doesn't inflate), missing-id (lists no dataset), no-404 (a bad URL gets
# 200), no-page (nothing at /), wrong-page (an answer at /, but not the map page). The smoke test must refuse each.
import http.server, json, os, sys
mode, args = os.path.basename(sys.argv[0]), sys.argv[1:]
port, ids = int(args[args.index("--port") + 1]), [os.path.basename(a)[:-4] for a in args if a.endswith(".gpt")]
tile = open(sys.argv[0] + ".png", "rb").read()  # a real tile, for the modes that get tiles right
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        listed = [] if mode == "missing-id" else ids
        headers = {}
        if self.path == "/" and mode == "wrong-page":
            body = b"hello"
        elif self.path == "/" and mode != "no-page":  # the map page, as much of it as the smoke test reads
            body = b'<script src="/app.js"></script>'
            headers = {"Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'"}
        elif self.path == "/api/datasets":
            body = json.dumps({"datasets": [{"id": i} for i in listed]}, separators=(",", ":")).encode()
        elif self.path.startswith("/tiles/"):
            body = b"not a png" if mode == "bad-tiles" else tile
            if mode == "corrupt-png":  # the right size, signature and CRCs, but its image data doesn't inflate
                import struct, zlib
                at = tile.index(b"IDAT")
                n = struct.unpack(">I", tile[at - 4:at])[0]
                data = tile[at + 4:at + 6] + bytes(b ^ 0x55 for b in tile[at + 6:at + 4 + n])
                body = tile[:at + 4] + data + struct.pack(">I", zlib.crc32(b"IDAT" + data)) + tile[at + 8 + n:]
        else:
            body = b"ok" if mode == "no-404" else None
        self.send_response(200 if body else 404)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body or b"")
    def log_message(self, *args):
        pass
server = http.server.HTTPServer(("127.0.0.1", port), Handler)
print(f"gpstiles serve: http://127.0.0.1:{server.server_port}/", flush=True)
server.serve_forever()
PY
for mode in bad-tiles corrupt-png missing-id no-404 no-page wrong-page; do
    [ "$mode" = bad-tiles ] || cp "$work/bin/bad-tiles" "$work/bin/$mode"
    build/gpstiles render "$work/tiny.gpt" 0 0 0 -o "$work/bin/$mode.png" > /dev/null || fail "can't draw a tile"
done
# A release from before the map page (step 5b): the dataset list, tiles, 404 for everything else, and no
# page in the program. Its tile is read from a fixed path, as a deploy copies only the program.
cat > "$work/bin/old-release" <<'PY'
#!/usr/bin/env python3
import http.server, json, os, sys
args = sys.argv[1:]
port, ids = int(args[args.index("--port") + 1]), [os.path.basename(a)[:-4] for a in args if a.endswith(".gpt")]
tile = open("@TILE@", "rb").read()
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (json.dumps({"datasets": [{"id": i} for i in ids]}, separators=(",", ":")).encode() if self.path == "/api/datasets"
                else tile if self.path.startswith("/tiles/") else None)
        self.send_response(200 if body else 404)
        self.end_headers()
        self.wfile.write(body or b"")
    def log_message(self, *args):
        pass
server = http.server.HTTPServer(("127.0.0.1", port), Handler)
print(f"gpstiles serve: http://127.0.0.1:{server.server_port}/", flush=True)
server.serve_forever()
PY
build/gpstiles render "$work/tiny.gpt" 0 0 0 -o "$work/bin/old-release.png" > /dev/null || fail "can't draw a tile"
sed -i '' "s|@TILE@|$work/bin/old-release.png|" "$work/bin/old-release"
# Two launchctls whose first bootstrap says "Bootstrap failed: 5", as launchd's did in real deploys: one that
# didn't load the job (flaky), one that loaded it anyway (loads-anyway).
mkdir -p "$work/flaky" "$work/loads-anyway"
printf '#!/bin/sh\nif [ "$1" = bootstrap ] && [ ! -e %q ]; then\n    touch %q\n    echo "Bootstrap failed: 5: Input/output error" >&2\n    exit 5\nfi\nexec /bin/launchctl "$@"\n' \
    "$work/flaky/failed" "$work/flaky/failed" > "$work/flaky/launchctl"
printf '#!/bin/sh\nif [ "$1" = bootstrap ] && [ ! -e %q ]; then\n    touch %q\n    /bin/launchctl "$@"\n    echo "Bootstrap failed: 5: Input/output error" >&2\n    exit 5\nfi\nexec /bin/launchctl "$@"\n' \
    "$work/loads-anyway/failed" "$work/loads-anyway/failed" > "$work/loads-anyway/launchctl"
chmod +x "$work/flaky/launchctl" "$work/loads-anyway/launchctl"
# And one where the old job takes a moment to go: for 1.5 s after a bootout, print still finds it and a
# bootstrap fails. It logs every bootstrap, to show the deploy waited instead of trying blindly.
mkdir -p "$work/lingers"
printf '%s\n' '#!/bin/sh' \
    "out=$work/lingers/out calls=$work/lingers/calls" \
    'recent() { [ -e "$out" ] && python3 -I -c "import os, sys, time; sys.exit(time.time() - os.path.getmtime(sys.argv[1]) > 1.5)" "$out"; }' \
    'case $1 in' \
    'bootout) /bin/launchctl "$@"; status=$?; touch "$out"; exit $status ;;' \
    'print) recent && exit 0 ;;' \
    'bootstrap) echo bootstrap >> "$calls"; if recent; then echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; fi ;;' \
    'esac' \
    'exec /bin/launchctl "$@"' > "$work/lingers/launchctl"
chmod +x "$work/lingers/launchctl"
cat > "$work/bin/hangs-ignoring-term" <<'PY'
#!/usr/bin/env python3
# Listens and never answers, and ignores SIGTERM: the pre-flight must still stop it (SIGKILL).
import signal, socket, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
args = sys.argv[1:]
s = socket.socket()
s.bind(("127.0.0.1", int(args[args.index("--port") + 1])))
s.listen(16)
print(f"gpstiles serve: http://127.0.0.1:{s.getsockname()[1]}/", flush=True)
time.sleep(3600)
PY
cat > "$work/bin/hangs" <<'PY'
#!/usr/bin/env python3
# Listens and says its address, then never answers (a deadlock): the smoke test must not hang.
import socket, sys, time
args = sys.argv[1:]
s = socket.socket()
s.bind(("127.0.0.1", int(args[args.index("--port") + 1])))
s.listen(16)
print(f"gpstiles serve: http://127.0.0.1:{s.getsockname()[1]}/", flush=True)
time.sleep(3600)
PY
chmod +x "$work/bin/"* || exit 1

# 1. A first install that fails as the service leaves nothing.
deploy test-first "$work/bin/fails-as-service" && fail "a release that fails as the service was accepted"
[ -z "$(current)" ] && [ ! -e "$GPSTILES_AGENTS/$GPSTILES_LABEL.plist" ] || fail "a failed first install left current or the launchd file"
launchctl print "$DOMAIN/$GPSTILES_LABEL" > /dev/null 2>&1 && fail "a failed first install left the service loaded"
ok "a failed first install leaves nothing installed"

# 2. A good release goes live.
deploy test-good-1 build/gpstiles || fail "the good release didn't deploy: $(tail -3 "$work/deploy.out")"
[ "$(current)" = releases/test-good-1 ] || fail "current isn't the good release"
ok "good release live on 127.0.0.1:$GPSTILES_PORT: $(grep 'smoke test green' "$work/deploy.out" | sed 's/^deploy: //')"

# 3. A release name is never reused (it may be the one running).
cp build/gpstiles "$work/bin/other" && printf 'x' >> "$work/bin/other" # a different program that still works
deploy test-good-1 "$work/bin/other" && fail "a release name was reused"
grep -q "already exists" "$work/deploy.out" || fail "no clear message: $(tail -1 "$work/deploy.out")"
cmp -s "$GPSTILES_HOME/releases/test-good-1/gpstiles" build/gpstiles || fail "the running release was overwritten"
ok "a reused release name is refused, the running release untouched"

# 4. A release that works alone but fails as the service: rolled back, previous kept as it was.
deploy test-service-fails "$work/bin/fails-as-service" && fail "a release failing as the service was accepted"
[ "$(current)" = releases/test-good-1 ] && [ ! -L "$GPSTILES_HOME/previous" ] || fail "not rolled back cleanly: current=$(current)"
tools/deploy.sh smoke > /dev/null || fail "the rolled-back service doesn't answer"
ok "a release failing as the service is rolled back to test-good-1, which answers"

# 5–7. Programs that exit at once, serve bad tiles, list no dataset, answer 200 for a bad URL, have no map page or
# a wrong one, hang, or
# hang and ignore SIGTERM are refused before the service is touched, and none is left running.
start=$(date +%s)
for bad in exits bad-tiles corrupt-png missing-id no-404 no-page wrong-page hangs hangs-ignoring-term; do
    deploy "test-$bad" "$work/bin/$bad" && fail "the $bad program was accepted"
    grep -q "pre-flight" "$work/deploy.out" || fail "the $bad program wasn't caught by the pre-flight: $(tail -2 "$work/deploy.out")"
    [ "$(current)" = releases/test-good-1 ] || fail "the $bad program changed current"
done
seconds=$(($(date +%s) - start))
[ $seconds -lt 90 ] || fail "refusing them took $seconds s"
pgrep -f "$work/bin/" > /dev/null && fail "a refused program is still running: $(pgrep -fl "$work/bin/")"
tools/deploy.sh smoke > /dev/null || fail "the service doesn't answer after the refused releases"
ok "9 bad programs refused in the pre-flight ($seconds s), none left running, the service untouched"

# 7b. A deploy interrupted (SIGTERM) after the switch puts the old release back and unlocks.
GPSTILES_RELEASE=test-interrupted GPSTILES_BINARY=$work/bin/fails-as-service tools/deploy.sh deploy > "$work/deploy.out" 2>&1 &
deployer=$!
for _ in $(seq 100); do
    grep -q "is current; smoke testing" "$work/deploy.out" && break
    sleep 0.1
done
grep -q "is current; smoke testing" "$work/deploy.out" || fail "the interrupted deploy never switched: $(tail -2 "$work/deploy.out")"
kill -TERM "$deployer"
wait "$deployer" 2> /dev/null
[ "$(current)" = releases/test-good-1 ] && [ ! -e "$GPSTILES_HOME/.lock" ] || fail "after SIGTERM: current=$(current), lock $(ls -d "$GPSTILES_HOME/.lock" 2> /dev/null)"
tools/deploy.sh smoke > /dev/null || fail "the service doesn't answer after the interrupted deploy"
ok "a deploy killed after the switch puts test-good-1 back, unlocked and answering"

# 8. A bad datasets.conf is refused, the service untouched.
cp "$GPSTILES_HOME/datasets.conf" "$work/datasets.good"
echo "data/build/tdrive.gpt" >> "$GPSTILES_HOME/datasets.conf"
deploy test-relative build/gpstiles && fail "a relative path in datasets.conf was accepted"
grep -q "not an absolute path" "$work/deploy.out" || fail "no clear message: $(tail -1 "$work/deploy.out")"
cp "$work/datasets.good" "$GPSTILES_HOME/datasets.conf"
tools/deploy.sh smoke > /dev/null || fail "the service doesn't answer after the refused datasets.conf"
ok "a relative path in datasets.conf is refused, the service untouched"

# 8b. Bad settings (a port that can't exist) are refused before anything changes.
GPSTILES_PORT=65536 deploy test-port build/gpstiles && fail "port 65536 was accepted"
grep -q "bad port" "$work/deploy.out" || fail "port 65536 wasn't refused up front: $(tail -1 "$work/deploy.out")"
tools/deploy.sh smoke > /dev/null || fail "the service doesn't answer after the refused port"
ok "a bad port setting is refused, the service untouched"

# 8c. Changing the port of the installed service is refused (a rollback would check the wrong port).
other_port=$(python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
GPSTILES_PORT=$other_port deploy test-moved build/gpstiles && fail "the port of the installed service was changed"
grep -q "installed on another port" "$work/deploy.out" || fail "no clear message: $(tail -1 "$work/deploy.out")"
tools/deploy.sh smoke > /dev/null || fail "the service doesn't answer after the refused port change"
ok "moving the installed service to another port is refused (undeploy first)"

# 9. Another program on the port is refused (it would answer the smoke test in the service's place).
launchctl bootout "$DOMAIN/$GPSTILES_LABEL" 2> /dev/null
build/gpstiles serve --port "$GPSTILES_PORT" "$work/tiny.gpt" > "$work/plain.log" 2>&1 &
plain=$!
sleep 0.5
deploy test-good-2 build/gpstiles && fail "a deploy went ahead with another program on the port"
grep -q "used by another program" "$work/deploy.out" || fail "no clear message: $(tail -1 "$work/deploy.out")"
kill "$plain" && wait "$plain" 2> /dev/null
plain=
ok "another program on the port is refused"

# 10–11. Two good releases, then `rollback` swaps them.
deploy test-good-2 build/gpstiles || fail "test-good-2 didn't deploy: $(tail -3 "$work/deploy.out")"
[ "$(current)" = releases/test-good-2 ] && [ "$(readlink "$GPSTILES_HOME/previous")" = releases/test-good-1 ] || fail "wrong links after test-good-2"
tools/deploy.sh rollback > "$work/deploy.out" 2>&1 || fail "rollback failed: $(tail -2 "$work/deploy.out")"
[ "$(current)" = releases/test-good-1 ] && [ "$(readlink "$GPSTILES_HOME/previous")" = releases/test-good-2 ] || fail "rollback didn't swap the releases"
ok "rollback swaps test-good-2 and test-good-1, and the service answers"

# 11b. A rollback whose smoke test fails swaps back (a previous release that fails under launchd).
cp "$GPSTILES_HOME/releases/test-good-2/gpstiles" "$work/good-2.saved"
cp "$work/bin/fails-as-service" "$GPSTILES_HOME/releases/test-good-2/gpstiles"
tools/deploy.sh rollback > "$work/deploy.out" 2>&1 && fail "a rollback to a broken release succeeded"
[ "$(current)" = releases/test-good-1 ] && [ "$(readlink "$GPSTILES_HOME/previous")" = releases/test-good-2 ] || fail "the failed rollback didn't swap back"
cp "$work/good-2.saved" "$GPSTILES_HOME/releases/test-good-2/gpstiles"
tools/deploy.sh smoke > /dev/null || fail "the service doesn't answer after the failed rollback"
ok "a rollback to a broken release swaps back to test-good-1, which answers"

# 11c. A release from before the map page (step 5b) deploys, and a rollback to it works: the smoke test
# looks for the page only in a program that has it.
deploy test-old-release "$work/bin/old-release" || fail "a release without the page was refused: $(tail -2 "$work/deploy.out")"
grep -q "no map page (a release from before step 6)" "$work/deploy.out" || fail "no word of the missing page: $(tail -1 "$work/deploy.out")"
deploy test-good-3 build/gpstiles || fail "test-good-3 didn't deploy: $(tail -3 "$work/deploy.out")"
tools/deploy.sh rollback > "$work/deploy.out" 2>&1 || fail "the rollback to the release without the page failed: $(tail -2 "$work/deploy.out")"
[ "$(current)" = releases/test-old-release ] || fail "rolled back to $(current), not test-old-release"
tools/deploy.sh rollback > "$work/deploy.out" 2>&1 || fail "the rollback to test-good-3 failed: $(tail -2 "$work/deploy.out")"
[ "$(current)" = releases/test-good-3 ] && grep -q "the map page" "$work/deploy.out" || fail "test-good-3 isn't back with its page"
ok "a release from before the map page deploys, is rolled back to, and forward again"

# 11d. A bootstrap that fails once (as launchd's did in 2 of 3 real deploys of step 6) is tried again.
PATH="$work/flaky:$PATH" deploy test-good-4 build/gpstiles || fail "a bootstrap that failed once wasn't tried again: $(tail -3 "$work/deploy.out")"
[ -e "$work/flaky/failed" ] && [ "$(current)" = releases/test-good-4 ] || fail "the bootstrap didn't fail once, or test-good-4 isn't current: $(current)"
ok "a bootstrap that fails once is tried again: test-good-4 live"

# 11e. A bootstrap that says it failed but loaded the job anyway counts as done (trying again would fail).
PATH="$work/loads-anyway:$PATH" deploy test-good-5 build/gpstiles || fail "a job that loaded anyway wasn't taken: $(tail -3 "$work/deploy.out")"
[ -e "$work/loads-anyway/failed" ] && [ "$(current)" = releases/test-good-5 ] || fail "the bootstrap didn't report an error, or test-good-5 isn't current: $(current)"
ok "a bootstrap that reports an error but loads the job counts: test-good-5 live"

# 11f. An old job that takes a moment to go is waited for: one bootstrap, after it has gone.
PATH="$work/lingers:$PATH" deploy test-good-6 build/gpstiles || fail "the deploy with a lingering old job failed: $(tail -3 "$work/deploy.out")"
[ "$(current)" = releases/test-good-6 ] && [ "$(wc -l < "$work/lingers/calls" | tr -d ' ')" = 1 ] ||
    fail "not one bootstrap after the old job went: $(wc -l < "$work/lingers/calls" | tr -d ' ') bootstraps, current $(current)"
ok "an old job that lingers 1.5 s is waited for: one bootstrap, test-good-6 live"

# 12. launchd restarts a killed server (KeepAlive).
old_pid=$(launchctl print "$DOMAIN/$GPSTILES_LABEL" | awk '/^\tpid = / {print $3}')
kill -9 "$old_pid" || fail "can't kill the service (pid $old_pid)"
tools/deploy.sh smoke > /dev/null || fail "no answer after the server was killed"
new_pid=$(launchctl print "$DOMAIN/$GPSTILES_LABEL" | awk '/^\tpid = / {print $3}')
[ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ] || fail "the killed server wasn't restarted (pid $old_pid → $new_pid)"
ok "a killed server is restarted by launchd (pid $old_pid → $new_pid)"

# 12b. `launchctl kickstart -k` restarts it too (DESIGN §12.2).
launchctl kickstart -k "$DOMAIN/$GPSTILES_LABEL" || fail "kickstart failed"
tools/deploy.sh smoke > /dev/null || fail "no answer after kickstart -k"
kick_pid=$(launchctl print "$DOMAIN/$GPSTILES_LABEL" | awk '/^\tpid = / {print $3}')
[ -n "$kick_pid" ] && [ "$kick_pid" != "$new_pid" ] || fail "kickstart -k didn't restart the server (pid $new_pid → $kick_pid)"
ok "back up after launchctl kickstart -k (pid $new_pid → $kick_pid)"

# 13. status answers quickly, and says so only when the service answers.
start=$(date +%s)
tools/deploy.sh status > "$work/status.out" 2>&1
grep -q "^deploy: answering on" "$work/status.out" && [ $(($(date +%s) - start)) -lt 15 ] || fail "status: $(cat "$work/status.out")"
ok "status: $(grep '^deploy: answering on' "$work/status.out" | sed 's/^deploy: //')"

# 14. undeploy, then nothing is left, and status says so.
tools/deploy.sh undeploy > /dev/null || fail "undeploy failed"
launchctl print "$DOMAIN/$GPSTILES_LABEL" > /dev/null 2>&1 && fail "the test service is still loaded"
tools/deploy.sh status > "$work/status.out" 2>&1
grep -q "^deploy: not answering on" "$work/status.out" || fail "status after undeploy: $(cat "$work/status.out")"
cleanup
[ ! -e "$work" ] || fail "$work is still there"
ok "test service removed, nothing left in build/deploy-test"
echo "DEPLOY-TEST PASSED"
