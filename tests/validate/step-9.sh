#!/bin/bash
# step-9.sh: validates step 9 (DESIGN §12.2) before approval:
#  - `make release-test` builds the package in build/release-test/ (no tag, dist/ unchanged); its unpacked
#    gpstiles imports a 10-row CSV, builds it, serves it on a free port and passes the smoke test on its own;
#    the archive holds plain files only (read with Python's tarfile, not macOS tar, which hides ._ files);
#  - a real release (make release VERSION=0.0.1) in a clean throwaway git repo, a copy of this one: an annotated
#    tag on its commit, a checksum shasum accepts, the commit built (not the folder); refused again, with an
#    untracked file, inside another repo or outside git, and bad versions refused before anything is built or
#    removed; a release that fails late (dist/ unwritable, no tag) leaves nothing; VERSION never runs as code;
#  - the stage 1 numbers: T-Drive imported and built (timed, peak memory) and `gpstiles bench`.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

tmp=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-step9.XXXXXX") || fail "no temp folder"
trap 'rm -rf "$tmp"' EXIT
tags_before=$(git tag 2> /dev/null | sort)
dist_before=$(cd dist 2> /dev/null && shasum -a 256 * 2> /dev/null)
# With a sanitizer in the environment's link flags and in a variable on make's command line (which make passes
# on to sub-makes in MAKEFLAGS): the release build must take neither (release.sh checks the program's libraries
# and symbols, and fails otherwise). B keeps this make's build-config stamp out of build/.
output=$(LDLIBS=-fsanitize=address make --no-print-directory -s release-test B="$tmp/flags" \
    ALL_CFLAGS="-fsanitize=address -O1 -Isrc -Itests" 2>&1) || fail "make release-test failed: $(echo "$output" | tail -3)"
echo "$output" | grep -q '^release: smoke test green on the unpacked package' || fail "no green smoke test: $output"
ok "$(echo "$output" | grep '^release: smoke test green')"
package=$(ls build/release-test/gpstiles-test-macos-*.tar.gz 2> /dev/null)
[ -s "$package" ] || fail "no test package in build/release-test/"
want="LEAFLET-LICENSE README.md gpstiles"
[ -f LICENSE ] && want="LEAFLET-LICENSE LICENSE README.md gpstiles"
contents=$(python3 -I - "$package" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1]) as t:
    members = t.getmembers()
top = {m.name.split("/")[0] for m in members}
odd = [m.name for m in members if m.pax_headers or m.uid or m.gid or m.uname not in ("root", "") or "/._" in "/" + m.name]
files = sorted(m.name.split("/", 1)[1] for m in members if "/" in m.name)
print(" ".join(files) if len(top) == 1 and not odd else f"top {sorted(top)} odd {odd} files {files}")
PY
)
[ "$contents" = "$want" ] || fail "the package holds: $contents"
ok "package $(basename "$package"): $contents, plain files owned by root ($(du -h "$package" | cut -f1 | tr -d ' '))"
[ "$(git tag 2> /dev/null | sort)" = "$tags_before" ] || fail "release-test made a git tag"
[ "$(cd dist 2> /dev/null && shasum -a 256 * 2> /dev/null)" = "$dist_before" ] || fail "release-test changed dist/"
ok "no tag made, dist/ as it was"

# A real release, in a throwaway git repo (a copy of this tree, its own .git): never in this repo.
try=$tmp/repo # the repo; its logs go beside it, not in it (an untracked file would stop the release)
mkdir -p "$try" && rsync -a --exclude /data --exclude /build --exclude /dist --exclude /.git --exclude /.review --exclude /.claude ./ "$try/" &&
    echo "a license, for the check" > "$try/LICENSE" && (cd "$try" && git init -q && git add -A && git -c user.name=step9 -c user.email=step9@example.invalid commit -qm "step 9 check") ||
    fail "can't make the throwaway repo"
mkdir -p "$try/build/release-0.1.0" "$try/build/validate/sentinel" && touch "$try/build/validate/sentinel/kept" ||
    fail "can't set up $try"
for bad in "0.1.0/../validate/sentinel" "../x" "1.2" "1.2.3-rc1" "v1.2.3" "1.2.3 "; do
    (cd "$try" && bash tools/release.sh "$bad" > /dev/null 2>&1) && fail "release.sh accepted version '$bad'"
done
[ -e "$try/build/validate/sentinel/kept" ] && [ -z "$(git -C "$try" tag)" ] || fail "a refused version removed files or made a tag"
ok "versions that aren't x.y.z digits are refused in a clean repo: nothing built, removed or tagged"
(cd "$try" && make --no-print-directory -s release VERSION=0.0.1 > "$tmp/release.out" 2>&1) ||
    fail "make release VERSION=0.0.1 failed: $(tail -2 "$tmp/release.out")"
[ "$(git -C "$try" cat-file -t v0.0.1)" = tag ] && [ "$(git -C "$try" rev-parse 'v0.0.1^{commit}')" = "$(git -C "$try" rev-parse HEAD)" ] ||
    fail "v0.0.1 isn't an annotated tag on the release's commit"
(cd "$try/dist" && shasum -a 256 -c gpstiles-0.0.1-macos-*.tar.gz.sha256 > /dev/null 2>&1) || fail "shasum doesn't accept the checksum"
pkg=$(cd "$try/dist" && ls gpstiles-0.0.1-macos-*.tar.gz)
[ "$(cat "$try/dist/$pkg.sha256")" = "$(shasum -a 256 "$try/dist/$pkg" | cut -d' ' -f1)  $pkg" ] ||
    fail "the checksum line isn't the hash, two spaces and the bare file name: $(cat "$try/dist/$pkg.sha256")"
python3 -I -c 'import sys, tarfile; sys.exit(not any(m.name.endswith("/LICENSE") for m in tarfile.open(sys.argv[1])))' \
    "$(ls "$try"/dist/gpstiles-0.0.1-macos-*.tar.gz)" || fail "the package lacks the repo's LICENSE"
(cd "$try" && bash tools/release.sh 0.0.1 > /dev/null 2>&1) && fail "a second release 0.0.1 was made"
# A release builds the commit, not the folder: a source edit git was told not to see stays out of it.
printf '\nint gpstiles_hidden_edit(void);\nint gpstiles_hidden_edit(void) { return 1; }\n' >> "$try/src/geo.c" &&
    git -C "$try" update-index --skip-worktree src/geo.c || fail "can't hide an edit"
(cd "$try" && bash tools/release.sh 0.0.5 > /dev/null 2>&1) || fail "release 0.0.5 failed"
nm "$try/build/release-0.0.5/obj/gpstiles" | grep -q gpstiles_hidden_edit && fail "an edit outside the commit reached the release"
git -C "$try" update-index --no-skip-worktree src/geo.c && git -C "$try" checkout -q src/geo.c || fail "can't undo the hidden edit"
# A tag that can't be made (signing on, with a signer that always fails): no tag, no files, and a retry works.
git -C "$try" config tag.gpgSign true && git -C "$try" config gpg.program false || fail "can't break signing"
(cd "$try" && bash tools/release.sh 0.0.6 > /dev/null 2>&1) && fail "a release was made without its tag"
[ -z "$(git -C "$try" tag -l v0.0.6)" ] && [ -z "$(ls -A "$try/dist" | grep 0.0.6)" ] || fail "the failed tag left a tag or files (.part)"
git -C "$try" config --unset tag.gpgSign && (cd "$try" && bash tools/release.sh 0.0.6 > /dev/null 2>&1) || fail "the retry of 0.0.6 failed"
# A source file the Makefile's wildcard would compile, not in the commit, and hidden from a plain git status:
printf '/* extra.c: not committed. */\nint gpstiles_extra(void);\nint gpstiles_extra(void) { return 0; }\n' > "$try/src/extra.c"
git -C "$try" config status.showUntrackedFiles no
(cd "$try" && bash tools/release.sh 0.0.2 > /dev/null 2>&1) && fail "a release with an untracked source file was made"
rm -f "$try/src/extra.c"
# A dist/ that can't be written: no tag, no files, and the same version works once it can.
chmod 555 "$try/dist" || fail "can't lock $try/dist"
(cd "$try" && bash tools/release.sh 0.0.4 > /dev/null 2>&1) && fail "a release into an unwritable dist/ was made"
[ -z "$(git -C "$try" tag -l v0.0.4)" ] && [ -z "$(ls "$try/dist" | grep 0.0.4)" ] || fail "the failed release left a tag or files"
chmod 755 "$try/dist" && (cd "$try" && bash tools/release.sh 0.0.4 > /dev/null 2>&1) || fail "the retry of 0.0.4 failed"
# VERSION is never run as shell code by make.
(cd "$try" && make --no-print-directory -s release "VERSION=9.9.9; touch $tmp/injected" > /dev/null 2>&1) &&
    fail "make release took a version with shell code"
[ ! -e "$tmp/injected" ] || fail "make release ran shell code from VERSION"

# A copy of the source inside another repo is not a repo of its own: a release from it would tag the outer repo's
# commit. Refused whether the outer repo ignores the copy (here in its build/) or holds it in a commit (a
# monorepo), and no tag made there.
rsync -a --exclude /.git --exclude /build --exclude /dist "$try/" "$try/build/inner/" || fail "can't copy into $try/build/inner"
(cd "$try/build/inner" && bash tools/release.sh 0.0.7 > /dev/null 2>&1) && fail "a release was made from an ignored folder inside another repo"
rsync -a --exclude /.git --exclude /build --exclude /dist --exclude /inner "$try/" "$try/inner/" && git -C "$try" add inner &&
    git -C "$try" -c user.name=step9 -c user.email=step9@example.invalid commit -qm "inner copy" || fail "can't commit a copy inside $try"
(cd "$try/inner" && bash tools/release.sh 0.0.8 > /dev/null 2>&1) && fail "a release was made from a committed folder inside another repo"
[ -z "$(git -C "$try" tag -l 'v0.0.[78]')" ] || fail "the outer repo got a tag"

# Outside a git work tree a release is refused before it builds or writes anything.
mkdir -p "$tmp/nogit/tools" && cp tools/release.sh "$tmp/nogit/tools/" || fail "can't set up $tmp/nogit"
(cd "$tmp/nogit" && bash tools/release.sh 0.0.3 > /dev/null 2>&1) && fail "a release was made outside git"
[ ! -e "$tmp/nogit/dist" ] && [ ! -e "$tmp/nogit/build" ] || fail "a refused release outside git left files"
ok "make release in a throwaway repo: an annotated tag on its commit, a checksum line shasum -c accepts, the LICENSE packed, the commit built (not a hidden edit); refused again, with an untracked file, inside another repo or outside git; an unwritable dist/ or a failing tag leaves nothing (retry works); make release runs no shell code from VERSION"

# The stage 1 numbers (speed, not pass/fail): T-Drive imported and built from the raw files, timed with peak
# memory, and how fast tiles are drawn at each zoom (gpstiles bench, 100 renders a zoom). SKIPPED without data/.
if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED (the stage 1 numbers): no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
out=$ROOT/build/validate/step-9
rm -rf "$out" && mkdir -p "$out" || fail "can't make $out"
timed() { # label, command...: runs it under /usr/bin/time -l, prints seconds and peak memory
    local label=$1
    shift
    /usr/bin/time -l "$@" > "$out/$label.out" 2> "$out/$label.time" || fail "$label failed: $(tail -2 "$out/$label.time")"
    awk -v label="$label" -v said="$(head -1 "$out/$label.out")" '
        / real / { seconds = $1 } /maximum resident set size/ { mb = $1 / 1048576 }
        END { printf "  ok  %s: %s s (warm file cache), peak memory %.0f MB · %s\n", label, seconds, mb, said }' "$out/$label.time"
}
# shellcheck disable=SC2046 # the names have no spaces
timed import build/gpstiles import --lon-col 3 --lat-col 4 -o "$out/tdrive.pts" $(ls data/raw/tdrive_txt/*.txt | LC_ALL=C sort)
timed build build/gpstiles build -o "$out/tdrive.gpt" "$out/tdrive.pts"
build/gpstiles bench "$out/tdrive.gpt" > "$out/bench.txt" || fail "bench failed"
awk 'NR == 1 { next } $1 == 0 || $1 == 5 || $1 == 10 || $1 == 11 || $1 == 13 || $1 == 15 || $1 == 18 || $1 == 24 {
        printf "  ok  bench zoom %2d (%3d tiles): p50 %s ms · p99 %s ms · max %s ms · %s points a render\n", $1, $3, $4, $5, $6, $7 }' "$out/bench.txt"
rm -f "$out/tdrive.pts" "$out/tdrive.gpt" # 160 MB: the numbers are kept, the files aren't
