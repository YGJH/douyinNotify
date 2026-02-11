#!/usr/bin/env bash
set -euo pipefail

# merge.sh - Convert audio streams to AAC (192k) while copying video streams,
# and merge multiple MKV parts into a single MKV using mkvmerge.
#
# Usage:
#   ./merge.sh part1.mkv part2.mkv [... partN.mkv]
# Output:
#   By default writes ./FullMerged-YYYYMMDD-HHMMSS.mkv
#
# Notes:
# - Requires: ffmpeg, mkvmerge, mktemp
# - This script is written for bash to avoid zsh array-indexing pitfalls.

err() { printf '%s\n' "$*" >&2; }

usage() {
  cat <<EOF
Usage: $0 <part1.mkv> <part2.mkv> [... <partN.mkv>]

Converts each input's audio to AAC (192k) while copying video streams,
then concatenates them with mkvmerge into a single MKV.

Requirements: ffmpeg, mkvmerge
EOF
}

# Check dependencies
for cmd in ffmpeg mkvmerge mktemp; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "Required command not found: $cmd"
    exit 2
  fi
done

if [ "$#" -lt 2 ]; then
  usage
  exit 1
fi

# Collect inputs (all args are treated as input parts)
inputs=("$@")
num_inputs=${#inputs[@]}

# Validate inputs
for idx in "${!inputs[@]}"; do
  f="${inputs[$idx]}"
  if [ ! -f "$f" ]; then
    err "Input does not exist or is not a regular file: $f"
    exit 1
  fi
done

# Create temporary working directory
TMPDIR="$(mktemp -d --suffix=.merge 2>/dev/null || mktemp -d)"
cleanup() {
  # safest removal
  if [ -n "${TMPDIR:-}" ] && [ -d "$TMPDIR" ]; then
    rm -rf -- "$TMPDIR"
  fi
}
trap cleanup EXIT INT TERM

err "Using temporary directory: $TMPDIR"

# Prepare temporary output filenames and convert audio
tmp_files=()
ffmpeg_opts=(-hide_banner -loglevel info -y)

for idx in "${!inputs[@]}"; do
  inpath="${inputs[$idx]}"
  outpath="${TMPDIR}/part-$((idx+1)).mkv"
  err "Converting [$((idx+1))/$num_inputs]: '$inpath' -> '$outpath'"
  # Convert audio to AAC (192k) and copy video stream
  ffmpeg "${ffmpeg_opts[@]}" -i "$inpath" -c:v copy -c:a aac -b:a 192k "$outpath"
  tmp_files+=("$outpath")
done

# Build mkvmerge arguments with '+' separators:
# Example: mkvmerge -o out file1 + file2 + file3
merge_args=()
for idx in "${!tmp_files[@]}"; do
  if [ "$idx" -eq 0 ]; then
    merge_args+=("${tmp_files[$idx]}")
  else
    merge_args+=("+")
    merge_args+=("${tmp_files[$idx]}")
  fi
done

out_name="FullMerged-$(date +%Y%m%d-%H%M%S).mkv"
out_path="./${out_name}"

err "Merging ${#tmp_files[@]} parts into: $out_path"
# Execute mkvmerge
mkvmerge -o "$out_path" "${merge_args[@]}"

err "Merge finished: $out_path"
# TMPDIR will be removed by trap on exit
