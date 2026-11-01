#!/usr/bin/env sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${1:-"$repo/build/host-ninja"}
if [ ! -f "$build_dir/CMakeCache.txt" ]; then
    "$repo/scripts/bootstrap-host.sh" "$build_dir"
fi
cmake --build "$build_dir" --parallel

