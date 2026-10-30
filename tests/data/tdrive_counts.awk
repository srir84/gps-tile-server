# tdrive_counts.awk: DESIGN §8's row rules in awk, for T-Drive (columns 3 and 4, comma-separated).
# The independent count `make check-data` compares `gpstiles import` with (TESTING.md §6).
# Run with LC_ALL=C so length() counts bytes.
BEGIN {
    FS = ","
    NUM = "^[-+]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][-+]?[0-9]+)?$"
    MAX_LAT = 85.05112877980659
}
{ bytes = length($0); sub(/\r$/, "") }
$0 == "" { next }
{ rows++ }
bytes > 65536 || $3 !~ NUM || $4 !~ NUM { malformed++; next }
$3 + 0 == 0 && $4 + 0 == 0 { zero++; next }
$3 < -180 || $3 > 180 || $4 < -MAX_LAT || $4 > MAX_LAT { out_of_range++; next }
{ imported++ }
END {
    printf "rows=%d imported=%d skipped_zero=%d skipped_out_of_range=%d skipped_malformed=%d\n",
        rows, imported, zero, out_of_range, malformed
}
