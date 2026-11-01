#!/usr/bin/env sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${1:-"$repo/build/host-benchmark"}
if [ ! -f "$build_dir/CMakeCache.txt" ]; then
    cmake -S "$repo" -B "$build_dir" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DAMUN_BUILD_TESTS=OFF \
        -DAMUN_BUILD_TOOLS=ON \
        -DAMUN_BUILD_3DS_PLATFORM_TESTS=OFF
fi
cmake --build "$build_dir" --parallel --target amun-bench
exec "$build_dir/amun-bench"
