# row_counts.awk: DESIGN §8's row rules in awk, for any comma-separated dataset: the independent count
# `make check-data` compares `gpstiles import` with (TESTING.md §6). The columns and the header lines to
# skip at the start of each file come in as variables, as in `gpstiles import`:
#   LC_ALL=C awk -v LON=3 -v LAT=4 [-v SKIP=N] -f row_counts.awk FILE...
# LC_ALL=C so that length() counts bytes. Limit: macOS's awk ends a line at a NUL byte, so data with NUL bytes needs
# another answer source (none of ours has any).
BEGIN {
    FS = ","
    NUM = "^[-+]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][-+]?[0-9]+)?$"
    MAX_LAT = 85.05112877980659
}
FNR <= SKIP { next }
{ bytes = length($0); sub(/\r$/, "") }
$0 == "" { next }
{ rows++ }
bytes > 65536 || $LON !~ NUM || $LAT !~ NUM { malformed++; next }
# As numbers: a field like 1e999 overflows, and macOS's awk then compares the field as text.
{ lon = $LON + 0; lat = $LAT + 0 }
lon == 0 && lat == 0 { zero++; next }
lon < -180 || lon > 180 || lat < -MAX_LAT || lat > MAX_LAT { out_of_range++; next }
{ imported++ }
END {
    printf "rows=%d imported=%d skipped_zero=%d skipped_out_of_range=%d skipped_malformed=%d\n",
        rows, imported, zero, out_of_range, malformed
}
