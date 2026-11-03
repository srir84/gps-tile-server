#!/bin/bash
# fetch-ais.sh: downloads NOAA's AIS ship positions (MarineCadastre, no account) for a range of 2023 days, one zip a
# day, into OUT_DIR (DESIGN §12.6, step 15). A day is kept only when its size = the server's Content-Length and
# `unzip -t` finds it whole; it is written under a temporary name first. Rerun to resume: kept days are skipped.
# Usage: tools/fetch-ais.sh OUT_DIR FIRST_DAY LAST_DAY   (days as YYYY-MM-DD, both included)
# AIS_URL: the server (the tests use a fake one); by default MarineCadastre's.
set -u
out=${1:?usage: tools/fetch-ais.sh OUT_DIR FIRST_DAY LAST_DAY}
first=${2:?usage}
last=${3:?usage}
base=${AIS_URL:-https://coast.noaa.gov/htdata/CMSP/AISDataHandler}

# Day $1 plus $2 days (0 or 1), with macOS's date or else GNU's (Linux).
add_days() {
    date -j -v+"$2"d -f %Y-%m-%d "$1" +%Y-%m-%d 2> /dev/null || date -u -d "$1 + $2 day" +%Y-%m-%d 2> /dev/null
}
# A real day only: macOS's date turns 2023-02-29 into 03-01, so a day must read back the same.
real_day() {
    [[ $1 =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [ "$(add_days "$1" 0)" = "$1" ]
}
real_day "$first" && real_day "$last" && [[ ! "$first" > "$last" ]] ||
    { echo "fetch-ais: want two real days, YYYY-MM-DD, the first not after the last" >&2; exit 2; }
mkdir -p "$out" || exit 1
part=
fetcher=
# A stopped run leaves no half file and no download running on (curl runs as a child the trap can stop).
trap 'if [ -n "$fetcher" ]; then kill "$fetcher" 2> /dev/null; fi; if [ -n "$part" ]; then rm -f "$part"; fi' EXIT
trap 'exit 1' INT TERM HUP
one_csv() { # a zip holding exactly one file, a CSV
    [ "$(unzip -Z1 "$1" 2> /dev/null | grep -c '\.csv$')" = 1 ] && [ "$(unzip -Z1 "$1" 2> /dev/null | wc -l | tr -d ' ')" = 1 ]
}
day=$first
while :; do
    name=AIS_${day//-/_}.zip
    url=$base/${day%%-*}/$name
    # A kept day must still be whole: one CSV, every byte as zipped (unzip -t: about 3 s a day; a damaged one is fetched again).
    if [ ! -f "$out/$name" ] || ! one_csv "$out/$name" || ! unzip -tq "$out/$name" > /dev/null 2>&1; then
        # The size the server will send: the last answer's, after redirects, only if it is 200 (a 404 page has a size).
        want=$(curl -sIL --retry 3 --max-time 60 "$url" | tr -d '\r' |
            awk '/^HTTP\// { status = $2; size = "" } tolower($1) == "content-length:" { size = $2 }
                 END { if (status == "200" && size != "") print size }')
        [ -n "$want" ] || { echo "fetch-ais: no $url" >&2; exit 1; }
        sleep 1
        part=$out/$name.part
        curl -sSL --fail --retry 3 --max-time 3600 -o "$part" "$url" &
        fetcher=$!
        wait "$fetcher"
        got=$?
        fetcher=
        if [ "$got" = 0 ] && [ "$(stat -f %z "$part")" = "$want" ] && unzip -tq "$part" > /dev/null && one_csv "$part"; then
            mv "$part" "$out/$name" || { echo "fetch-ais: can't keep $name" >&2; exit 1; } # the trap removes .part
            part=
            echo "$name $want"
        else
            echo "fetch-ais: $name failed" >&2
            exit 1
        fi
    fi
    [ "$day" = "$last" ] && break
    day=$(add_days "$day" 1) || { echo "fetch-ais: date failed after $day" >&2; exit 1; }
done
echo "fetch-ais: $(ls "$out"/AIS_*.zip | wc -l | tr -d ' ') days in $out"
