#!/usr/bin/env sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=${AMUN_VERSION:-0.1.0}
exec python3 "$repo/scripts/package-release.py" \
    --version "$version" \
    --3gx "$repo/3ds/AMUN.3gx" \
    --elf "$repo/3ds/AMUN.elf" \
    --map-file "$repo/3ds/AMUN.map" \
    --require-3gx \
    "$@"
