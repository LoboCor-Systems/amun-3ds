#!/usr/bin/env sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${1:-"$repo/build/host-ninja"}
"$repo/scripts/build-host.sh" "$build_dir"
ctest --test-dir "$build_dir" --output-on-failure
cd "$repo"
python3 -B -m unittest discover -v

