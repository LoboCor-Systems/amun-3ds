#!/usr/bin/env sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${1:-"$repo/build/host-ninja"}
command -v cmake >/dev/null
command -v python3 >/dev/null
cmake -S "$repo" -B "$build_dir" -G Ninja -DCMAKE_BUILD_TYPE=Debug

