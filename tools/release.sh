#!/bin/bash
# release.sh: a package others can install (TESTING.md §12.7). Usage:
#   tools/release.sh test             package + smoke test in build/release-test/, no tag (before approval)
#   tools/release.sh VERSION          dist/gpstiles-VERSION-macos-<arch>.tar.gz + .sha256 + local tag vVERSION
#                                     (approved commit, clean tree). Nothing is uploaded anywhere.
# The build is optimized, for macOS 13 or later, with only the system's libraries (checked). Smoke test: the
# package is unpacked into a temp folder, and the unpacked gpstiles imports a 10-row CSV, builds it, serves it
# on a free port and answers like the deploy smoke test. A release writes dist/ only once its tag is made.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd -P)
MIN_MACOS=13.0

die() {
    echo "release: $*" >&2
    exit 1
}

version=${1:-}
# Checked before anything else, and exactly: the version becomes part of paths that are removed below.
[ "$version" = test ] || [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "usage: tools/release.sh test | x.y.z (digits only)"
if [ "$version" != test ]; then
    # git must answer: a git that fails must not look like a clean tree or an unused tag.
    git rev-parse --is-inside-work-tree > /dev/null 2>&1 || die "not in a git work tree"
    [ "$(cd "$(git rev-parse --show-toplevel)" && pwd -P)" = "$ROOT" ] || die "$ROOT is not the top of its own git repo"
    changes=$(git status --porcelain --untracked-files=normal) || die "git status failed"
    [ -z "$changes" ] || die "the tree has changes: release only an approved, committed step"
    git check-ref-format "refs/tags/v$version" || die "v$version can't be a tag name"
    git rev-parse -q --verify "refs/tags/v$version" > /dev/null && die "tag v$version already exists"
    commit=$(git rev-parse --verify HEAD) || die "no commit to release"
fi

# An optimized build of its own: the compiler, flags and libraries are set here, not taken from the
# environment or from the make command that ran this (MAKEFLAGS), so the package never holds a sanitizer or
# debug build. A release builds the commit's own
# files (git archive): nothing outside the commit (an ignored file, an edit git was told not to see) can
# reach it. release-test builds the working folder, to test it before its commit.
work=$ROOT/build/release-$version
rm -rf "$work" && mkdir -p "$work/obj" || exit 1
src=$ROOT
if [ "$version" != test ]; then
    src=$work/src
    mkdir -p "$src" && git archive "$commit" | tar -x -C "$src" || die "can't export $commit"
fi
env -u MAKEFLAGS -u MFLAGS -u CFLAGS -u LDFLAGS -u LDLIBS -u CC \
    make -C "$src" --no-print-directory -s B="$work/obj" CC=cc LDLIBS="-lm -lz" MODE_FLAGS="-O2 -mmacosx-version-min=$MIN_MACOS" all \
    > "$work/make.log" 2>&1 || die "build failed: $work/make.log"
libraries=$(otool -L "$work/obj/gpstiles" | tail -n +2 | awk '{print $1}' | LC_ALL=C sort | tr '\n' ' ')
[ "$libraries" = "/usr/lib/libSystem.B.dylib /usr/lib/libz.1.dylib " ] || die "the program links $libraries"
nm "$work/obj/gpstiles" | grep -q "__asan\|__ubsan" && die "the program holds sanitizer code"
otool -l "$work/obj/gpstiles" | grep -q "minos $MIN_MACOS" || die "the program isn't built for macOS $MIN_MACOS"

arch=$(uname -m)
name=gpstiles-$([ "$version" = test ] && echo test || echo "$version")-macos-$arch
stage=$work/$name
mkdir -p "$stage" || exit 1
cp "$work/obj/gpstiles" "$src/README.md" "$stage/" || exit 1
cp "$src/www/leaflet/LICENSE" "$stage/LEAFLET-LICENSE" || exit 1
if [ -f "$src/LICENSE" ]; then
    cp "$src/LICENSE" "$stage/" || exit 1
fi
# Plain files only: no macOS metadata (._ files, extended attributes) and no local user or uid in the archive.
COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs --uid 0 --gid 0 --uname root --gname wheel \
    -C "$work" -czf "$work/$name.tar.gz" "$name" || exit 1

# Smoke test the unpacked package on its own.
smoke=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-release.XXXXXX") || exit 1
server=
cleanup() {
    if [ -n "$server" ]; then
        kill "$server" 2> /dev/null
        wait "$server" 2> /dev/null
    fi
    rm -rf "$smoke"
}
trap cleanup EXIT
tar -C "$smoke" -xzf "$work/$name.tar.gz" || die "can't unpack the package"
bin=$smoke/$name/gpstiles
printf 'lon,lat\n116.39,39.90\n116.40,39.91\n116.41,39.92\n116.42,39.93\n116.43,39.94\n116.44,39.95\n116.45,39.96\n116.46,39.97\n116.47,39.98\n116.48,39.99\n' > "$smoke/ten.csv"
"$bin" import --lon-col 1 --lat-col 2 --skip 1 -o "$smoke/ten.pts" "$smoke/ten.csv" > "$smoke/import.out" ||
    die "the packaged gpstiles can't import"
grep -q "imported=10 " "$smoke/import.out" || die "import said: $(cat "$smoke/import.out")"
"$bin" build -o "$smoke/ten.gpt" "$smoke/ten.pts" > /dev/null || die "the packaged gpstiles can't build"
"$bin" serve --port 0 "$smoke/ten.gpt" > "$smoke/serve.log" 2>&1 &
server=$!
port=
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$smoke/serve.log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || die "the packaged server didn't start: $(cat "$smoke/serve.log")"
url=http://127.0.0.1:$port
CURL=(curl -q -s --noproxy '*' --connect-timeout 2 --max-time 10) # no ~/.curlrc, bounded, never through a proxy
"${CURL[@]}" -f "$url/api/datasets" | grep -q '"id":"ten","points":10,' || die "smoke: /api/datasets doesn't list ten with 10 points"
"${CURL[@]}" -f -o "$smoke/tile.png" "$url/tiles/ten/0/0/0.png" && python3 -I tools/png_check.py "$smoke/tile.png" 2> /dev/null ||
    die "smoke: tile 0/0/0 is not a whole 256 x 256 PNG"
[ "$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$url/no-such-page")" = 404 ] || die "smoke: a bad URL isn't 404"
"${CURL[@]}" -f "$url/" | grep -q 'src="/app.js"' || die "smoke: / is not the map page"
"${CURL[@]}" -f "$url/api/datasets/ten/count?bbox=116,39,117,40" | grep -q '"count":10}' || die "smoke: the count API doesn't find the 10 points"
[ "$("${CURL[@]}" -f "$url/api/datasets/ten/export.csv?bbox=116,39,117,40" | wc -l | tr -d ' ')" = 11 ] ||
    die "smoke: the export isn't 10 rows and a header"
echo "release: smoke test green on the unpacked package ($url)"

if [ "$version" = test ]; then
    echo "release: test package $work/$name.tar.gz (no tag, nothing in dist/)"
    exit 0
fi
# The package and its checksum go into dist/ under temporary names first, then the tag on the commit
# checked above, then the files take their names. Any failure undoes the steps before it: no half release,
# and no tag left to block a retry.
(cd "$work" && shasum -a 256 "$name.tar.gz" > "$name.tar.gz.sha256") || exit 1
staged=(dist/".$name.tar.gz.part" dist/".$name.tar.gz.sha256.part")
mkdir -p dist && cp "$work/$name.tar.gz" "${staged[0]}" && cp "$work/$name.tar.gz.sha256" "${staged[1]}" ||
    { rm -f "${staged[@]}"; die "can't write dist/: nothing released"; }
undo_release() { # from the tag to the final names: a stop leaves neither the tag nor files
    git tag -d "v$version" > /dev/null 2>&1
    rm -f "${staged[@]}" "dist/$name.tar.gz" "dist/$name.tar.gz.sha256"
}
trap 'undo_release; echo "release: interrupted: nothing released" >&2; exit 1' INT TERM HUP
git tag -a "v$version" -m "gpstiles $version" "$commit" || { rm -f "${staged[@]}"; die "can't tag v$version: nothing released"; }
if ! { mv "${staged[0]}" "dist/$name.tar.gz" && mv "${staged[1]}" "dist/$name.tar.gz.sha256"; }; then
    undo_release
    die "can't finish dist/: tag v$version removed, nothing released"
fi
trap - INT TERM HUP
echo "release: dist/$name.tar.gz · dist/$name.tar.gz.sha256 · local tag v$version on $commit (not pushed)"
