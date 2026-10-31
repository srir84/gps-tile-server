#!/bin/bash
# deploy.sh: the local service on this Mac (TESTING.md §12.6): a launchd user agent that runs
# `gpstiles serve` on the .gpt files in datasets.conf. Usage: tools/deploy.sh deploy|rollback|undeploy|status|smoke
#   deploy    check datasets.conf, smoke-test the new program on its own (pre-flight), then copy it to
#             releases/<commit>-<time>, switch `current`, restart, smoke-test the service; anything red or
#             an interruption before the smoke test passes puts back what was there and exits 1
#   rollback  switch `current` and `previous`, restart, smoke test
#   undeploy  stop the service and remove its launchd file (releases and logs are kept)
#   status    the service, its pid, the release, whether it answers
# Settings (tests change them; the defaults are the real service):
#   GPSTILES_HOME     install folder                         (~/.local/gpstiles)
#   GPSTILES_LABEL    launchd label                          (local.gpstiles.serve)
#   GPSTILES_PORT     port on 127.0.0.1                      (8080)
#   GPSTILES_AGENTS   folder for the launchd file            (~/Library/LaunchAgents)
#   GPSTILES_BINARY   program to install                     (build/gpstiles)
#   GPSTILES_RELEASE  release name                           (commit[-dirty]-YYYYmmddHHMMSS)
#   GPSTILES_THROTTLE seconds before launchd restarts it     (10)
set -u
cd "$(dirname "$0")/.." || exit 1

HOME_DIR=${GPSTILES_HOME:-$HOME/.local/gpstiles}
LABEL=${GPSTILES_LABEL:-local.gpstiles.serve}
PORT=${GPSTILES_PORT:-8080}
AGENTS=${GPSTILES_AGENTS:-$HOME/Library/LaunchAgents}
BINARY=${GPSTILES_BINARY:-build/gpstiles}
THROTTLE=${GPSTILES_THROTTLE:-10}
PLIST=$AGENTS/$LABEL.plist
DOMAIN=gui/$(id -u)
LOG=$HOME_DIR/logs/serve.log
# Bounded, direct requests: a server that never answers can't hang a deploy, and a proxy in the shell
# can't stand in for 127.0.0.1.
CURL=(curl -s --noproxy '*' --connect-timeout 2 --max-time 10)
# Exits 0 only for a complete 256 x 256 RGBA PNG: signature, chunk CRCs, IHDR first, IEND last, and the
# image data inflating to 256 rows of 1 + 1,024 bytes.
PNG_CHECK='
import struct, sys, zlib
d = open(sys.argv[1], "rb").read()
assert d[:8] == b"\x89PNG\r\n\x1a\n"
i, kinds, idat = 8, [], b""
while i < len(d):
    n, kind = struct.unpack(">I4s", d[i:i + 8])
    body = d[i + 8:i + 8 + n]
    assert len(body) == n and struct.unpack(">I", d[i + 8 + n:i + 12 + n])[0] == zlib.crc32(kind + body)
    kinds.append(kind)
    idat += body if kind == b"IDAT" else b""
    i += 12 + n
assert kinds[0] == b"IHDR" and kinds[-1] == b"IEND" and d[16:24] == struct.pack(">II", 256, 256)
assert len(zlib.decompress(idat)) == 256 * 1025
'

say() {
    echo "deploy: $*"
}

die() {
    echo "deploy: $*" >&2
    exit 1
}

# The paths go into a start script and a launchd file: plain characters only.
for path in "$HOME_DIR" "$AGENTS"; do
    case $path in
    /*) ;;
    *) die "$path must be an absolute path" ;;
    esac
    case $path in
    *[!A-Za-z0-9._/\ -]*) die "unsafe characters in $path (allowed: letters, digits, space . _ - /)" ;;
    esac
done
case $PORT$THROTTLE in
'' | *[!0-9]*) die "bad port '$PORT' or throttle '$THROTTLE'" ;;
esac
[ "${#PORT}" -le 5 ] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "bad port '$PORT' (1 to 65535)"
[ "${#THROTTLE}" -le 4 ] && [ "$THROTTLE" -ge 1 ] && [ "$THROTTLE" -le 3600 ] || die "bad throttle '$THROTTLE' (1 to 3600)"
case $LABEL in
'' | *[!A-Za-z0-9._-]*) die "bad label '$LABEL'" ;;
esac

loaded() {
    launchctl print "$DOMAIN/$LABEL" > /dev/null 2>&1
}

service_pid() {
    launchctl print "$DOMAIN/$LABEL" 2> /dev/null | awk '/^\tpid = / {print $3}'
}

# The pid listening on the port, if any.
listener_pid() {
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2> /dev/null | head -1
}

# The .gpt files in datasets.conf, one path per line; blank lines and # comments are skipped.
datasets() {
    sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^$/d' "$HOME_DIR/datasets.conf"
}

# datasets.conf must list at least one readable file, by absolute path (launchd starts the service in /).
check_datasets() {
    [ -f "$HOME_DIR/datasets.conf" ] || { say "no $HOME_DIR/datasets.conf: write one .gpt path per line"; return 1; }
    local path n=0
    while IFS= read -r path; do
        case $path in
        /*) ;;
        *) say "datasets.conf: '$path' is not an absolute path"; return 1 ;;
        esac
        [ -f "$path" ] && [ -r "$path" ] || { say "datasets.conf: can't read '$path'"; return 1; }
        n=$((n + 1))
    done < <(datasets)
    [ $n -gt 0 ] || { say "datasets.conf lists no .gpt files"; return 1; }
}

# Smoke test of the server at a URL (TESTING.md §12.6): every dataset listed, tile 0/0/0 of each a real PNG,
# a bad URL → 404. Every request is bounded.
smoke_url() {
    local url=$1 list path id size code tile=$HOME_DIR/logs/smoke-tile.png
    list=$("${CURL[@]}" -f "$url/api/datasets") || { say "smoke: /api/datasets didn't answer"; return 1; }
    while IFS= read -r path; do
        id=$(basename "$path" .gpt)
        printf '%s' "$list" | grep -q "\"id\":\"$id\"" || { say "smoke: $id is not listed"; return 1; }
        # The whole tile, then decoded: every chunk's CRC, IEND last, the image data inflated to 256 rows.
        rm -f "$tile"
        "${CURL[@]}" -f -o "$tile" "$url/tiles/$id/0/0/0.png" || { say "smoke: tile 0/0/0 of $id didn't download"; return 1; }
        python3 -I -c "$PNG_CHECK" "$tile" 2> /dev/null || { say "smoke: tile 0/0/0 of $id is not a whole 256 x 256 PNG"; return 1; }
    done < <(datasets)
    code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$url/no-such-page")
    [ "$code" = 404 ] || { say "smoke: a bad URL answered '$code', not 404"; return 1; }
}

# The service passes when its own process (launchd's pid) listens on the port, within 15 s, and
# answers the smoke test. Another program on the port can't stand in for it.
smoke_service() {
    local pid listener tries=0
    while :; do
        pid=$(service_pid)
        listener=$(listener_pid)
        [ -n "$pid" ] && [ "$pid" = "$listener" ] && break
        tries=$((tries + 1))
        if [ $tries -ge 75 ]; then
            say "smoke: the service (pid ${pid:-none}) isn't listening on port $PORT (listener: ${listener:-none})"
            return 1
        fi
        sleep 0.2
    done
    smoke_url "http://127.0.0.1:$PORT" || return 1
    say "smoke test green: $(datasets | wc -l | tr -d ' ') dataset(s) listed and drawn, bad URL → 404, pid $pid (http://127.0.0.1:$PORT/)"
}

# Stops a process: TERM, then KILL if it is still there after 5 s (a program may ignore TERM).
stop_process() {
    kill "$1" 2> /dev/null || return 0
    for _ in $(seq 25); do
        kill -0 "$1" 2> /dev/null || break
        sleep 0.2
    done
    kill -9 "$1" 2> /dev/null
    wait "$1" 2> /dev/null
}

# Runs a program on the datasets on a free port and smoke-tests it, before the service is touched.
preflight() {
    local binary=$1 log=$HOME_DIR/logs/preflight.log files=() line port= pid status=1
    while IFS= read -r line; do
        files+=("$line")
    done < <(datasets)
    "$binary" serve --host 127.0.0.1 --port 0 "${files[@]}" > "$log" 2>&1 &
    pid=$!
    preflight_pid=$pid # stopped by the exit trap if the deploy is interrupted
    for _ in $(seq 50); do
        port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
        [ -n "$port" ] && break
        kill -0 "$pid" 2> /dev/null || break
        sleep 0.2
    done
    if [ -n "$port" ] && smoke_url "http://127.0.0.1:$port"; then
        status=0
    fi
    stop_process "$pid"
    preflight_pid=
    [ $status = 0 ] || say "pre-flight: the new program fails on these datasets. Its output: $(tail -3 "$log" | tr '\n' ' ')"
    return $status
}

# Writes the start script and the launchd file. The script reads datasets.conf at every start, so a
# changed list only needs a restart.
write_service() {
    mkdir -p "$AGENTS" "$HOME_DIR/logs" || return 1
    {
        echo '#!/bin/bash'
        echo "# Started by launchd ($LABEL): serves every .gpt in datasets.conf on 127.0.0.1:$PORT."
        echo 'set -u'
        printf 'home=%q\n' "$HOME_DIR"
        echo 'files=()'
        echo 'while IFS= read -r line; do'
        echo '    files+=("$line")'
        echo "done < <(sed -e 's/#.*//' -e 's/[[:space:]]*\$//' -e '/^\$/d' \"\$home/datasets.conf\")"
        echo "exec \"\$home/current/gpstiles\" serve --host 127.0.0.1 --port $PORT \"\${files[@]}\""
    } > "$HOME_DIR/serve.sh.new" && chmod +x "$HOME_DIR/serve.sh.new" && mv -f "$HOME_DIR/serve.sh.new" "$HOME_DIR/serve.sh" ||
        return 1
    cat > "$PLIST.new" <<EOF || return 1
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key><array><string>$HOME_DIR/serve.sh</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>$THROTTLE</integer>
    <key>StandardOutPath</key><string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    mv -f "$PLIST.new" "$PLIST"
}

# (Re)loads the service from its launchd file, so a changed file always takes effect.
restart() {
    if loaded; then
        launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null || return 1
    fi
    launchctl bootstrap "$DOMAIN" "$PLIST"
}

# Stops the service. Returns 1 if it is still loaded afterwards.
stop_service() {
    if loaded; then
        launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null
    fi
    ! loaded
}

link_to() {
    ln -sfn "$1" "$HOME_DIR/$2"
}

# Keeps the start script and launchd file as they are, for undo. A backup is published only once it is
# complete; returns 1 if one can't be written (nothing may change then).
save_service() {
    rm -f "$HOME_DIR/serve.sh.old" "$PLIST.old"
    if [ -f "$HOME_DIR/serve.sh" ]; then
        cp -p "$HOME_DIR/serve.sh" "$HOME_DIR/serve.sh.old.new" && mv -f "$HOME_DIR/serve.sh.old.new" "$HOME_DIR/serve.sh.old" ||
            return 1
    fi
    if [ -f "$PLIST" ]; then
        cp -p "$PLIST" "$PLIST.old.new" && mv -f "$PLIST.old.new" "$PLIST.old" || return 1
    fi
}

# The port can't change under an installed service: a rollback would check the wrong one.
check_port_unchanged() {
    [ ! -f "$HOME_DIR/serve.sh" ] || grep -q -- "--port $PORT " "$HOME_DIR/serve.sh" ||
        die "the service is installed on another port: run make undeploy first to change the port. Nothing changed"
}

# One deploy, rollback or undeploy at a time per installation. The lock goes with the exit trap.
lock() {
    mkdir -p "$HOME_DIR" || exit 1
    mkdir "$HOME_DIR/.lock" 2> /dev/null || die "another deploy, rollback or undeploy is running (or remove $HOME_DIR/.lock)"
    trap on_exit EXIT INT TERM HUP
}

# The exit trap: stops a pre-flight server, undoes a switch that hasn't passed its smoke test, unlocks.
on_exit() {
    local status=$?
    trap - EXIT INT TERM HUP
    [ -n "$preflight_pid" ] && stop_process "$preflight_pid"
    if [ "$switched" = 1 ]; then
        undo
        status=1
    fi
    rmdir "$HOME_DIR/.lock" 2> /dev/null
    exit $status
}

# Between switching `current` and a green smoke test, any exit (an error, Ctrl-C, a closed terminal)
# runs this: the old release back, or no service at all on a first install.
undo() {
    switched=0
    say "smoke test red or interrupted. The service log ends with: $(tail -3 "$LOG" 2> /dev/null | tr '\n' ' ')"
    if [ -n "$old_current" ]; then
        link_to "$old_current" current
        if [ -n "$old_previous" ]; then
            link_to "$old_previous" previous
        else
            rm -f "$HOME_DIR/previous"
        fi
        # The start script and launchd file as they were (the new settings may be what failed).
        [ -f "$HOME_DIR/serve.sh.old" ] && mv -f "$HOME_DIR/serve.sh.old" "$HOME_DIR/serve.sh"
        [ -f "$PLIST.old" ] && mv -f "$PLIST.old" "$PLIST"
        if restart && smoke_service; then
            say "rolled back to $old_current"
        else
            say "the rolled-back release fails its smoke test too: see $LOG"
        fi
    else
        stop_service || say "the service is still loaded: launchctl bootout gui/$(id -u)/$LABEL"
        rm -f "$HOME_DIR/current" "$HOME_DIR/previous" "$PLIST" "$PLIST.old" "$HOME_DIR/serve.sh.old"
        say "first install failed: nothing is installed"
    fi
}

deploy() {
    [ -x "$BINARY" ] || die "$BINARY not found: run make first"
    lock
    mkdir -p "$HOME_DIR/logs" "$HOME_DIR/releases" || exit 1
    check_port_unchanged
    check_datasets || die "nothing changed"
    preflight "$BINARY" || die "nothing changed"
    local listener
    listener=$(listener_pid)
    if [ -n "$listener" ] && [ "$listener" != "$(service_pid)" ]; then
        die "port $PORT is used by another program (pid $listener): stop it first. Nothing changed"
    fi
    local release=${GPSTILES_RELEASE:-}
    if [ -z "$release" ]; then
        release=$(git rev-parse --short HEAD 2> /dev/null) || die "not a git checkout: set GPSTILES_RELEASE"
        [ -z "$(git status --porcelain -- src www Makefile 2> /dev/null)" ] || release=$release-dirty
        release=$release-$(date +%Y%m%d%H%M%S)
    fi
    case $release in
    '' | *[!A-Za-z0-9._-]*) die "bad release name '$release'" ;;
    esac
    # Never overwrite a release: the one running, or the one to roll back to, may be it.
    [ ! -e "$HOME_DIR/releases/$release" ] || die "release $release already exists. Nothing changed"
    mkdir "$HOME_DIR/releases/$release" && cp "$BINARY" "$HOME_DIR/releases/$release/gpstiles" ||
        die "copy failed. Nothing changed"
    old_current=$(readlink "$HOME_DIR/current" 2> /dev/null)
    old_previous=$(readlink "$HOME_DIR/previous" 2> /dev/null)
    save_service || die "can't save the service files for a rollback. Nothing changed"
    switched=1
    link_to "releases/$release" current
    [ -n "$old_current" ] && link_to "$old_current" previous
    write_service || exit 1
    restart || exit 1
    say "release $release is current; smoke testing..."
    smoke_service || exit 1
    switched=0
    rm -f "$HOME_DIR/serve.sh.old" "$PLIST.old"
}

rollback() {
    lock
    local now before
    now=$(readlink "$HOME_DIR/current" 2> /dev/null)
    before=$(readlink "$HOME_DIR/previous" 2> /dev/null)
    [ -n "$before" ] && [ "$before" != "$now" ] || die "no previous release to roll back to"
    check_port_unchanged
    check_datasets || die "nothing changed"
    preflight "$HOME_DIR/$before/gpstiles" || die "the previous release fails on these datasets. Nothing changed"
    old_current=$now
    old_previous=$before
    save_service || die "can't save the service files. Nothing changed"
    switched=1 # a red smoke test or an interruption swaps them back (on_exit → undo)
    link_to "$before" current
    link_to "$now" previous
    write_service || exit 1
    restart || exit 1
    smoke_service || exit 1
    switched=0
    rm -f "$HOME_DIR/serve.sh.old" "$PLIST.old"
    say "rolled back to $before (previous is now $now)"
}

status() {
    if loaded; then
        say "service $LABEL: loaded, pid $(service_pid)"
    else
        say "service $LABEL: not loaded"
    fi
    [ -L "$HOME_DIR/current" ] && say "current: $(readlink "$HOME_DIR/current")"
    [ -L "$HOME_DIR/previous" ] && say "previous: $(readlink "$HOME_DIR/previous")"
    if "${CURL[@]}" -f -o /dev/null "http://127.0.0.1:$PORT/api/datasets"; then
        say "answering on http://127.0.0.1:$PORT/ (listener pid $(listener_pid))"
    else
        say "not answering on http://127.0.0.1:$PORT/"
    fi
}

old_current=
old_previous=
switched=0
preflight_pid=
case ${1:-} in
deploy) deploy ;;
rollback) rollback ;;
undeploy)
    lock
    stop_service || die "the service is still loaded: launchctl bootout failed (gui/$(id -u)/$LABEL)"
    rm -f "$PLIST"
    say "service $LABEL stopped and removed (files kept in $HOME_DIR)"
    ;;
status) status ;;
smoke) smoke_service ;;
*) die "usage: tools/deploy.sh deploy|rollback|undeploy|status|smoke" ;;
esac
