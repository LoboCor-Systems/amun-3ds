#!/usr/bin/env sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
deps=${AMUN_DEPS_DIR:-"$repo/build/3ds-deps"}
jobs=${AMUN_BUILD_JOBS:-4}

if [ -z "${DEVKITARM:-}" ]; then
    echo "DEVKITARM is not set; use the pinned devkitPro environment documented in docs/3ds-toolchain.md" >&2
    exit 1
fi

cmake -DAMUN_DEPS_DIR="$deps" -P "$repo/cmake/3ds/fetch_pinned_dependencies.cmake"
cmake -DAMUN_DEPS_DIR="$deps" -DAMUN_BUILD_JOBS="$jobs" \
    -P "$repo/cmake/3ds/build_pinned_dependencies.cmake"
make -C "$repo/3ds" AMUN_DEPS_DIR="$deps" -j "$jobs"
cmake -DAMUN_3GX="$repo/3ds/AMUN.3gx" -P "$repo/cmake/3ds/verify_3gx.cmake"

echo "Cross-compiled: $repo/3ds/AMUN.3gx"
echo "Hardware tested: no (run docs/hardware-test.md)"
