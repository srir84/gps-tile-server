# lib.sh: helpers shared by tests/validate/step-N.sh (TESTING.md §12.4). Sourced, not run.
# Deliberate breaks happen only in a scratch copy, never in the real tree.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NAME=$(basename "$0" .sh)

# Leftover git variables (e.g. from a hook) would point git at the real repo.
for name in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do
    unset "$name"
done

fail() {
    echo "FAIL $NAME: $*"
    exit 1
}

ok() {
    echo "  ok  $*"
}

# Copies the repo, without build/, data/, dist/, .git and .review, to a temp folder that is
# deleted on exit, and moves there. Logs go to $SCRATCH/log.
scratch_copy() {
    SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-$NAME.XXXXXX") || exit 1
    trap 'rm -rf "$SCRATCH"' EXIT
    mkdir "$SCRATCH/repo" || exit 1
    # Top-level names only: BSD tar's --exclude ./data would also drop tests/data.
    local item
    for item in "$ROOT"/* "$ROOT"/.[!.]*; do
        case ${item##*/} in build | data | dist | .git | .review | '.[!.]*') continue ;; esac
        cp -R "$item" "$SCRATCH/repo/" || fail "copy failed"
    done
    cd "$SCRATCH/repo" || exit 1
}

# The deliberately failing test: one passing check in tests/unit/test_runner.c made false.
break_unit_test() {
    local file=tests/unit/test_runner.c
    sed 's/CHECK(1 + 1 == 2);/CHECK(1 + 1 == 3);/' "$file" > "$file.new" && mv "$file.new" "$file"
    grep -q 'CHECK(1 + 1 == 3);' "$file" || fail "could not insert the failing test"
}

# Imports and builds T-Drive into build/validate/ with the current gpstiles, once: reused while newer
# than build/gpstiles. Sets TDRIVE_PTS and TDRIVE_GPT. Needs data/raw/tdrive_txt (check before calling).
tdrive_gpt() {
    TDRIVE_PTS=$ROOT/build/validate/tdrive.pts
    TDRIVE_GPT=$ROOT/build/validate/tdrive.gpt
    if [ "$TDRIVE_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$TDRIVE_PTS" -nt "$ROOT/build/gpstiles" ]; then
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$TDRIVE_PTS" "$TDRIVE_GPT"
    # Relative paths: 8,911 absolute ones could pass the argument size limit.
    (cd "$ROOT" && build/gpstiles import --lon-col 3 --lat-col 4 -o "$TDRIVE_PTS" data/raw/tdrive_txt/*.txt > /dev/null) ||
        fail "T-Drive import failed"
    "$ROOT/build/gpstiles" build -o "$TDRIVE_GPT" "$TDRIVE_PTS" > /dev/null || fail "T-Drive build failed"
}

# Imports and builds tdrive-sample, the first 500 T-Drive files in name order, into build/validate/ the same
# way (step 5a: a second, smaller dataset). Sets TDRIVE_SAMPLE_GPT. Needs data/raw/tdrive_txt.
tdrive_sample_gpt() {
    TDRIVE_SAMPLE_GPT=$ROOT/build/validate/tdrive-sample.gpt
    local pts=$ROOT/build/validate/tdrive-sample.pts
    if [ "$TDRIVE_SAMPLE_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$pts" -nt "$ROOT/build/gpstiles" ]; then
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$pts" "$TDRIVE_SAMPLE_GPT"
    # shellcheck disable=SC2046 # the names have no spaces
    (cd "$ROOT" && build/gpstiles import --lon-col 3 --lat-col 4 -o "$pts" $(ls data/raw/tdrive_txt/*.txt | sort | head -500) > /dev/null) ||
        fail "tdrive-sample import failed"
    "$ROOT/build/gpstiles" build -o "$TDRIVE_SAMPLE_GPT" "$pts" > /dev/null || fail "tdrive-sample build failed"
}

# GeoLife's data folder (step 10): 182 user folders, each with Trajectory/*.plt.
GEOLIFE_DATA="$ROOT/data/raw/geolife/Geolife Trajectories 1.3/Data"

# Imports and builds GeoLife (all 18,670 .plt files: 6 header lines, latitude first) into build/validate/ the same
# way. Sets GEOLIFE_PTS, GEOLIFE_GPT and GEOLIFE_COUNTS (the line import printed). Needs $GEOLIFE_DATA.
geolife_gpt() {
    GEOLIFE_PTS=$ROOT/build/validate/geolife.pts
    GEOLIFE_GPT=$ROOT/build/validate/geolife.gpt
    local counts=$ROOT/build/validate/geolife.counts key=$ROOT/build/validate/geolife.key
    local options="--lat-col 1 --lon-col 2 --skip 6" now
    # What the result depends on besides the program: the options, and every file's name, size and time.
    now=$(cd "$GEOLIFE_DATA" && { echo "$options"; ls -lnT */Trajectory/*.plt; } | shasum -a 256) || fail "can't list GeoLife"
    if [ "$GEOLIFE_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$GEOLIFE_PTS" -nt "$ROOT/build/gpstiles" ] &&
        [ "$counts" -nt "$ROOT/build/gpstiles" ] && [ "$(cat "$key" 2> /dev/null)" = "$now" ]; then
        GEOLIFE_COUNTS=$(cat "$counts")
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$GEOLIFE_PTS" "$GEOLIFE_GPT" "$counts" "$key"
    # Relative names, from inside the data folder: 18,670 full paths would pass the argument size limit.
    # shellcheck disable=SC2086 # $options is several words
    (cd "$GEOLIFE_DATA" && "$ROOT/build/gpstiles" import $options -o "$GEOLIFE_PTS" */Trajectory/*.plt > "$counts") ||
        fail "GeoLife import failed"
    "$ROOT/build/gpstiles" build -o "$GEOLIFE_GPT" "$GEOLIFE_PTS" > /dev/null || fail "GeoLife build failed"
    echo "$now" > "$key"
    GEOLIFE_COUNTS=$(cat "$counts")
}

# The USGS earthquakes (step 11): tools/fetch-usgs.py's files and MANIFEST.txt.
USGS_DATA="$ROOT/data/raw/usgs"

# Imports and builds the earthquakes into build/validate/earthquakes.gpt the same way, kept while the options and the
# files are the same. Sets USGS_PTS, USGS_GPT and USGS_COUNTS. Needs $USGS_DATA/MANIFEST.txt.
usgs_gpt() {
    USGS_PTS=$ROOT/build/validate/earthquakes.pts
    USGS_GPT=$ROOT/build/validate/earthquakes.gpt
    local counts=$ROOT/build/validate/earthquakes.counts key=$ROOT/build/validate/earthquakes.key
    local options="--lat-col 2 --lon-col 3 --skip 1" now
    now=$(cd "$USGS_DATA" && { echo "$options"; ls -lnT usgs-*.csv; } | shasum -a 256) || fail "can't list the USGS files"
    if [ "$USGS_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$USGS_PTS" -nt "$ROOT/build/gpstiles" ] &&
        [ "$counts" -nt "$ROOT/build/gpstiles" ] && [ "$(cat "$key" 2> /dev/null)" = "$now" ]; then
        USGS_COUNTS=$(cat "$counts")
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$USGS_PTS" "$USGS_GPT" "$counts" "$key"
    # shellcheck disable=SC2086 # $options is several words
    (cd "$USGS_DATA" && "$ROOT/build/gpstiles" import $options -o "$USGS_PTS" usgs-*.csv > "$counts") ||
        fail "USGS import failed"
    "$ROOT/build/gpstiles" build -o "$USGS_GPT" "$USGS_PTS" > /dev/null || fail "USGS build failed"
    echo "$now" > "$key"
    USGS_COUNTS=$(cat "$counts")
}

# Porto's taxi trips (step 12): one CSV file, the points of a trip in its POLYLINE column (the 9th).
PORTO_DATA="$ROOT/data/raw/porto/train.csv"

# Imports and builds Porto into build/validate/porto.gpt with --mem 256M (several runs), kept while the file and the
# options are the same. Sets PORTO_PTS, PORTO_GPT, PORTO_COUNTS and PORTO_BUILD (build's line). Needs $PORTO_DATA.
porto_gpt() {
    PORTO_PTS=$ROOT/build/validate/porto.pts
    PORTO_GPT=$ROOT/build/validate/porto.gpt
    local counts=$ROOT/build/validate/porto.counts key=$ROOT/build/validate/porto.key
    local options="--polyline 9 --skip 1" now
    now=$({ echo "$options"; ls -lnT "$PORTO_DATA"; } | shasum -a 256) || fail "can't list Porto's file"
    if [ "$PORTO_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$PORTO_PTS" -nt "$ROOT/build/gpstiles" ] &&
        [ "$counts" -nt "$ROOT/build/gpstiles" ] && [ "$(cat "$key" 2> /dev/null)" = "$now" ]; then
        PORTO_COUNTS=$(sed -n 1p "$counts")
        PORTO_BUILD=$(sed -n 2p "$counts")
        return 0
    fi
    mkdir -p "$ROOT/build/validate/runs" || exit 1
    rm -f "$PORTO_PTS" "$PORTO_GPT" "$counts" "$key"
    # shellcheck disable=SC2086 # $options is several words
    "$ROOT/build/gpstiles" import $options -o "$PORTO_PTS" "$PORTO_DATA" > "$counts" || fail "Porto import failed"
    "$ROOT/build/gpstiles" build --mem 256M --tmp "$ROOT/build/validate/runs" -o "$PORTO_GPT" "$PORTO_PTS" >> "$counts" ||
        fail "Porto build failed"
    echo "$now" > "$key"
    PORTO_COUNTS=$(sed -n 1p "$counts")
    PORTO_BUILD=$(sed -n 2p "$counts")
}

# NYC's yellow-taxi trips 2009–2010 (step 14): TLC's Parquet files, turned into `lon,lat` rows by tools/nyc-taxi.py,
# which needs DuckDB in data/tools/venv.
NYC_DATA="$ROOT/data/raw/nyc-taxi"
NYC_PYTHON="$ROOT/data/tools/venv/bin/python"

# Imports and builds NYC into build/validate/nyc-taxi.gpt (5.4 GB), kept while the files are the same. Sets NYC_GPT and
# NYC_COUNTS. Needs $NYC_DATA's Parquet files and $NYC_PYTHON.
nyc_gpt() {
    NYC_GPT=$ROOT/build/validate/nyc-taxi.gpt
    local pts=$ROOT/build/validate/nyc-taxi.pts counts=$ROOT/build/validate/nyc-taxi.counts
    local key=$ROOT/build/validate/nyc-taxi.key now
    # What the result depends on besides the program: the files, the converter, DuckDB's version and import's options.
    now=$({ (cd "$NYC_DATA" && ls -lnT yellow_tripdata_20*.parquet); shasum -a 256 "$ROOT/tools/nyc-taxi.py";
        "$NYC_PYTHON" -I -c 'import duckdb; print(duckdb.__version__)'; echo "--lon-col 1 --lat-col 2 --skip 1"; } |
        shasum -a 256) || fail "can't list NYC's files"
    if [ "$NYC_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$counts" -nt "$ROOT/build/gpstiles" ] &&
        [ "$(cat "$key" 2> /dev/null)" = "$now" ]; then
        NYC_COUNTS=$(cat "$counts")
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$NYC_GPT" "$counts" "$key"
    "$NYC_PYTHON" -I "$ROOT/tools/nyc-taxi.py" "$NYC_DATA"/yellow_tripdata_20*.parquet |
        "$ROOT/build/gpstiles" import --lon-col 1 --lat-col 2 --skip 1 -o "$pts" /dev/stdin > "$counts"
    local status=("${PIPESTATUS[@]}")
    if [ "${status[0]}" != 0 ] || [ "${status[1]}" != 0 ]; then
        rm -f "$pts" "$counts" # a converter that stopped early leaves counts that look whole
        fail "NYC import failed (nyc-taxi.py ${status[0]}, import ${status[1]})"
    fi
    "$ROOT/build/gpstiles" build --tmp "$ROOT/build/validate" -o "$NYC_GPT" "$pts" > /dev/null ||
        { rm -f "$pts" "$counts"; fail "NYC build failed"; }
    rm -f "$pts"
    echo "$now" > "$key"
    NYC_COUNTS=$(cat "$counts")
}

# NOAA's AIS ship positions (step 15): one zip a day from tools/fetch-ais.sh, each holding one CSV (LAT 3rd, LON 4th).
AIS_DATA="$ROOT/data/raw/ais"

# Imports every day (streamed from its zip) into build/validate/ais/ (kept: 9.9 GB) and builds them into
# build/validate/ais-2023.gpt (9.7 GB) with the default --mem, kept while the zips, the program and the options are the
# same. Sets AIS_GPT, AIS_PTS_DIR, AIS_COUNTS (the days' counts added up) and AIS_BUILD (build's line). About 20
# minutes. Needs $AIS_DATA's zips.
ais_gpt() {
    AIS_GPT=$ROOT/build/validate/ais-2023.gpt
    AIS_PTS_DIR=$ROOT/build/validate/ais
    local dir=$AIS_PTS_DIR counts=$ROOT/build/validate/ais-2023.counts key=$ROOT/build/validate/ais-2023.key
    local options="--lat-col 3 --lon-col 4 --skip 1" now zip day
    # What the result depends on besides the program: the zips, the options and this function's own code.
    now=$( { (cd "$AIS_DATA" && ls -lnT AIS_2023_*.zip); echo "$options"; declare -f ais_gpt; } |
        shasum -a 256) || fail "can't list the AIS zips"
    if [ "$AIS_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$counts" -nt "$ROOT/build/gpstiles" ] &&
        [ "$(cat "$key" 2> /dev/null)" = "$now" ] &&
        [ "$(ls "$dir"/AIS_2023_*.pts 2> /dev/null | wc -l)" = "$(ls "$AIS_DATA"/AIS_2023_*.zip | wc -l)" ]; then
        AIS_COUNTS=$(sed -n 1p "$counts")
        AIS_BUILD=$(sed -n 2p "$counts")
        return 0
    fi
    rm -rf "$dir" "$AIS_GPT" "$counts" "$key"
    mkdir -p "$dir" || exit 1
    for zip in "$AIS_DATA"/AIS_2023_*.zip; do
        day=$(basename "$zip" .zip)
        # shellcheck disable=SC2086 # $options is several words
        unzip -p "$zip" | "$ROOT/build/gpstiles" import $options -o "$dir/$day.pts" /dev/stdin >> "$dir/days.txt"
        local status=("${PIPESTATUS[@]}")
        [ "${status[0]}" = 0 ] && [ "${status[1]}" = 0 ] || { rm -rf "$dir"; fail "AIS import of $day failed"; }
    done
    # The days' counts added up, in import's own words.
    awk '{ for (i = 1; i <= NF; i++) { split($i, kv, "="); sum[kv[1]] += kv[2] } }
         END { printf "rows=%d imported=%d skipped_zero=%d skipped_out_of_range=%d skipped_malformed=%d\n",
               sum["rows"], sum["imported"], sum["skipped_zero"], sum["skipped_out_of_range"], sum["skipped_malformed"] }' \
        "$dir/days.txt" > "$counts"
    "$ROOT/build/gpstiles" build --tmp "$ROOT/build/validate" -o "$AIS_GPT" "$dir"/AIS_2023_*.pts >> "$counts" ||
        { rm -rf "$dir" "$counts"; fail "AIS build failed"; }
    echo "$now" > "$key"
    AIS_COUNTS=$(sed -n 1p "$counts")
    AIS_BUILD=$(sed -n 2p "$counts")
}

# OpenStreetMap's public GPS traces of 2013 (step 16): one 22 GB tar.xz of GPX files.
OSM_DUMP="$ROOT/data/raw/osm-gps/gpx-planet-2013-04-09.tar.xz"

# Imports the whole dump (xz -dc | tar -xOf - | import --gpx) and builds it into build/validate/osm-gps.gpt with the
# default --mem, kept while the dump, the program and this function's code are the same. Sets OSM_GPT, OSM_COUNTS and
# OSM_BUILD. About an hour (the decompression). Needs $OSM_DUMP.
osm_gpt() {
    OSM_GPT=$ROOT/build/validate/osm-gps.gpt
    local pts=$ROOT/build/validate/osm-gps.pts counts=$ROOT/build/validate/osm-gps.counts
    local key=$ROOT/build/validate/osm-gps.key now
    now=$( { ls -lnT "$OSM_DUMP"; declare -f osm_gpt; } | shasum -a 256) || fail "can't list the OSM dump"
    if [ "$OSM_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$counts" -nt "$ROOT/build/gpstiles" ] &&
        [ "$(cat "$key" 2> /dev/null)" = "$now" ]; then
        OSM_COUNTS=$(sed -n 1p "$counts")
        OSM_BUILD=$(sed -n 2p "$counts")
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$OSM_GPT" "$pts" "$counts" "$key"
    xz -dc "$OSM_DUMP" | tar -xOf - | "$ROOT/build/gpstiles" import --gpx -o "$pts" /dev/stdin > "$counts"
    local status=("${PIPESTATUS[@]}")
    if [ "${status[0]}" != 0 ] || [ "${status[1]}" != 0 ] || [ "${status[2]}" != 0 ]; then
        rm -f "$pts" "$counts" # an early end leaves counts that look whole
        fail "OSM import failed (xz ${status[0]}, tar ${status[1]}, import ${status[2]})"
    fi
    "$ROOT/build/gpstiles" build --tmp "$ROOT/build/validate" -o "$OSM_GPT" "$pts" >> "$counts" ||
        { rm -f "$pts" "$counts"; fail "OSM build failed"; }
    rm -f "$pts"
    echo "$now" > "$key"
    OSM_COUNTS=$(sed -n 1p "$counts")
    OSM_BUILD=$(sed -n 2p "$counts")
}
