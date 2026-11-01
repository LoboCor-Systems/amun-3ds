"""Bounded local raw-memory dump search and comparison utilities."""

from __future__ import annotations

import math
import os
from pathlib import Path
import struct
from typing import Any


MAX_DUMP_BYTES = 512 * 1024 * 1024
FORMATS = {
    "u8": ("B", 1),
    "s8": ("b", 1),
    "u16": ("H", 2),
    "s16": ("h", 2),
    "u32": ("I", 4),
    "s32": ("i", 4),
    "f32": ("f", 4),
}


class DumpError(ValueError):
    pass


def _read(path: str | os.PathLike[str]) -> tuple[Path, bytes]:
    selected = Path(path).expanduser().resolve()
    try:
        size = selected.stat().st_size
        if size > MAX_DUMP_BYTES:
            raise DumpError(f"dump exceeds {MAX_DUMP_BYTES} byte safety limit")
        return selected, selected.read_bytes()
    except OSError as error:
        raise DumpError(f"cannot read dump {selected}: {error}") from error


def parse_value(value: str | int | float, value_type: str) -> int | float:
    if value_type not in FORMATS:
        raise DumpError(f"unsupported dump value type: {value_type}")
    try:
        parsed: int | float = float(value) if value_type == "f32" else int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as error:
        raise DumpError(f"invalid {value_type} value: {value!r}") from error
    code, size = FORMATS[value_type]
    try:
        struct.pack("<" + code, parsed)
    except (OverflowError, struct.error) as error:
        raise DumpError(f"value is outside {value_type} range") from error
    if isinstance(parsed, float) and not math.isfinite(parsed):
        raise DumpError("floating search value must be finite")
    return parsed


def search_dump(
    path: str | os.PathLike[str],
    *,
    value_type: str,
    value: str | int | float,
    base_address: int = 0,
    stride: int = 1,
    limit: int = 1000,
) -> dict[str, Any]:
    selected, data = _read(path)
    if stride <= 0 or limit <= 0:
        raise DumpError("stride and result limit must be positive")
    target = parse_value(value, value_type)
    code, size = FORMATS[value_type]
    matches: list[dict[str, Any]] = []
    total = 0
    for offset in range(0, len(data) - size + 1, stride):
        current = struct.unpack_from("<" + code, data, offset)[0]
        if current == target:
            total += 1
            if len(matches) < limit:
                matches.append({"address": f"0x{base_address + offset:08X}", "offset": offset, "value": current})
    return {
        "file": str(selected),
        "type": value_type,
        "value": target,
        "baseAddress": f"0x{base_address:X}",
        "stride": stride,
        "matchCount": total,
        "truncated": total > len(matches),
        "matches": matches,
    }


def diff_dumps(
    before_path: str | os.PathLike[str],
    after_path: str | os.PathLike[str],
    *,
    value_type: str,
    mode: str = "changed",
    base_address: int = 0,
    stride: int = 1,
    by: str | int | float | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    before_name, before = _read(before_path)
    after_name, after = _read(after_path)
    if value_type not in FORMATS:
        raise DumpError(f"unsupported dump value type: {value_type}")
    if mode not in {"changed", "unchanged", "increased", "decreased", "by"}:
        raise DumpError(f"unsupported diff mode: {mode}")
    if stride <= 0 or limit <= 0:
        raise DumpError("stride and result limit must be positive")
    delta = parse_value(by, value_type) if mode == "by" and by is not None else None
    if mode == "by" and delta is None:
        raise DumpError("by mode requires --by delta")
    code, size = FORMATS[value_type]
    common = min(len(before), len(after))
    matches: list[dict[str, Any]] = []
    total = 0
    for offset in range(0, common - size + 1, stride):
        old = struct.unpack_from("<" + code, before, offset)[0]
        new = struct.unpack_from("<" + code, after, offset)[0]
        matched = (
            old != new if mode == "changed" else
            old == new if mode == "unchanged" else
            new > old if mode == "increased" else
            new < old if mode == "decreased" else
            new - old == delta
        )
        if matched:
            total += 1
            if len(matches) < limit:
                matches.append(
                    {"address": f"0x{base_address + offset:08X}", "offset": offset, "before": old, "after": new}
                )
    return {
        "before": str(before_name),
        "after": str(after_name),
        "type": value_type,
        "mode": mode,
        "baseAddress": f"0x{base_address:X}",
        "stride": stride,
        "sizeMismatch": len(before) != len(after),
        "comparedBytes": common,
        "matchCount": total,
        "truncated": total > len(matches),
        "matches": matches,
    }
