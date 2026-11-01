"""Persistent memory snapshots and an offline, little-endian value scanner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
from typing import Iterator


SNAPSHOT_MAGIC = b"AMSNAP1\0"
SNAPSHOT_HEADER = struct.Struct("<I")
MAX_METADATA_BYTES = 1 << 20
MAX_SNAPSHOT_BYTES = 512 << 20
DEFAULT_MAX_CANDIDATES = 5_000_000


class ScanError(ValueError):
    """Raised for invalid snapshots or scan operations."""


@dataclass(frozen=True)
class ValueType:
    name: str
    struct_code: str
    size: int
    integral: bool
    signed: bool

    @property
    def format(self) -> str:
        return "<" + self.struct_code

    def decode(self, data: bytes, offset: int) -> int | float:
        return struct.unpack_from(self.format, data, offset)[0]

    def bits(self, data: bytes, offset: int) -> int:
        return int.from_bytes(data[offset : offset + self.size], "little", signed=False)

    def parse(self, text: str) -> int | float:
        text = text.strip()
        if not text:
            raise ScanError(f"A {self.name} value is required")
        try:
            value: int | float = int(text, 0) if self.integral else float(text)
        except ValueError as error:
            raise ScanError(f"Invalid {self.name} value: {text!r}") from error
        if self.integral:
            bits = self.size * 8
            minimum = -(1 << (bits - 1)) if self.signed else 0
            maximum = (1 << (bits - 1)) - 1 if self.signed else (1 << bits) - 1
            if not minimum <= int(value) <= maximum:
                raise ScanError(f"{value} is outside {self.name} range [{minimum}, {maximum}]")
        elif not math.isfinite(float(value)):
            raise ScanError("Scanner targets must be finite floating-point values")
        return value


VALUE_TYPES: dict[str, ValueType] = {
    "u8": ValueType("u8", "B", 1, True, False),
    "s8": ValueType("s8", "b", 1, True, True),
    "u16": ValueType("u16", "H", 2, True, False),
    "s16": ValueType("s16", "h", 2, True, True),
    "u32": ValueType("u32", "I", 4, True, False),
    "s32": ValueType("s32", "i", 4, True, True),
    "f32": ValueType("f32", "f", 4, False, True),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_base(base_address: int, data_size: int) -> None:
    if not isinstance(base_address, int) or base_address < 0:
        raise ScanError("Snapshot base address must be a non-negative integer")
    if base_address > 0xFFFFFFFFFFFFFFFF:
        raise ScanError("Snapshot base address exceeds 64-bit address space")
    if data_size > MAX_SNAPSHOT_BYTES:
        raise ScanError(
            f"Snapshot is {data_size} bytes; safety limit is {MAX_SNAPSHOT_BYTES} bytes"
        )
    if base_address + data_size > 0x10000000000000000:
        raise ScanError("Snapshot range exceeds 64-bit address space")


@dataclass(frozen=True)
class MemorySnapshot:
    data: bytes
    base_address: int = 0
    name: str = "snapshot"
    captured_at: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            object.__setattr__(self, "data", bytes(self.data))
        _validate_base(self.base_address, len(self.data))
        if not self.captured_at:
            object.__setattr__(self, "captured_at", _utc_now())

    @property
    def end_address(self) -> int:
        return self.base_address + len(self.data)

    def contains(self, address: int, size: int = 1) -> bool:
        return self.base_address <= address and address + size <= self.end_address

    def offset(self, address: int, size: int = 1) -> int:
        if not self.contains(address, size):
            raise ScanError(
                f"Address 0x{address:X} (+{size}) is outside snapshot "
                f"0x{self.base_address:X}-0x{self.end_address:X}"
            )
        return address - self.base_address

    @classmethod
    def from_raw_file(
        cls,
        path: str | os.PathLike[str],
        base_address: int = 0,
        name: str | None = None,
    ) -> "MemorySnapshot":
        source = Path(path).expanduser().resolve()
        try:
            size = source.stat().st_size
            _validate_base(base_address, size)
            data = source.read_bytes()
        except OSError as error:
            raise ScanError(f"Cannot read snapshot {source}: {error}") from error
        return cls(data, base_address, name or source.stem, source=str(source))

    def save(self, path: str | os.PathLike[str]) -> Path:
        destination = Path(path).expanduser().resolve()
        metadata = {
            "version": 1,
            "name": self.name,
            "capturedAt": self.captured_at,
            "source": self.source,
            "baseAddress": self.base_address,
            "size": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest(),
        }
        encoded = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            raise ScanError("Snapshot metadata is too large")
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w+b", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(SNAPSHOT_MAGIC)
                handle.write(SNAPSHOT_HEADER.pack(len(encoded)))
                handle.write(encoded)
                handle.write(self.data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "MemorySnapshot":
        source = Path(path).expanduser().resolve()
        try:
            with source.open("rb") as handle:
                if handle.read(len(SNAPSHOT_MAGIC)) != SNAPSHOT_MAGIC:
                    raise ScanError(f"Not an AMUN snapshot: {source}")
                header = handle.read(SNAPSHOT_HEADER.size)
                if len(header) != SNAPSHOT_HEADER.size:
                    raise ScanError("Truncated snapshot header")
                metadata_size = SNAPSHOT_HEADER.unpack(header)[0]
                if not 1 <= metadata_size <= MAX_METADATA_BYTES:
                    raise ScanError(f"Invalid snapshot metadata size: {metadata_size}")
                encoded = handle.read(metadata_size)
                if len(encoded) != metadata_size:
                    raise ScanError("Truncated snapshot metadata")
                try:
                    metadata = json.loads(encoded.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise ScanError(f"Invalid snapshot metadata: {error}") from error
                if not isinstance(metadata, dict) or metadata.get("version") != 1:
                    raise ScanError("Unsupported snapshot metadata version")
                expected_size = metadata.get("size")
                if not isinstance(expected_size, int) or not 0 <= expected_size <= MAX_SNAPSHOT_BYTES:
                    raise ScanError("Invalid snapshot data size")
                data = handle.read(expected_size + 1)
                if len(data) != expected_size:
                    raise ScanError("Snapshot data is truncated or has trailing bytes")
        except OSError as error:
            raise ScanError(f"Cannot load snapshot {source}: {error}") from error
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata.get("sha256"):
            raise ScanError("Snapshot checksum does not match its data")
        base = metadata.get("baseAddress")
        if not isinstance(base, int):
            raise ScanError("Snapshot base address is invalid")
        return cls(
            data=data,
            base_address=base,
            name=str(metadata.get("name", source.stem)),
            captured_at=str(metadata.get("capturedAt", "")),
            source=str(metadata.get("source", source)),
        )


@dataclass(frozen=True)
class ScanResult:
    address: int
    current: int | float
    previous: int | float | None = None


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "bit_changed": "bit_changed",
        "increased_by": "by",
        "decreased_by": "by",
    }
    normalized = aliases.get(normalized, normalized)
    supported = {
        "exact",
        "unknown",
        "changed",
        "unchanged",
        "increased",
        "decreased",
        "by",
        "between",
        "bit_changed",
    }
    if normalized not in supported:
        raise ScanError(f"Unsupported scan mode: {mode}")
    return normalized


class SnapshotScanner:
    """Stateful value scanner that refines candidates across snapshots."""

    def __init__(self, max_candidates: int = DEFAULT_MAX_CANDIDATES) -> None:
        if max_candidates <= 0:
            raise ScanError("max_candidates must be positive")
        self.max_candidates = max_candidates
        self.value_type: ValueType | None = None
        self.stride = 1
        self.snapshot: MemorySnapshot | None = None
        self.previous_snapshot: MemorySnapshot | None = None
        self.candidates: list[int] = []

    def clear(self) -> None:
        self.value_type = None
        self.snapshot = None
        self.previous_snapshot = None
        self.candidates.clear()

    def start(
        self,
        snapshot: MemorySnapshot,
        value_type: str,
        mode: str = "unknown",
        *,
        value: int | float | None = None,
        second: int | float | None = None,
        stride: int = 1,
    ) -> int:
        codec = VALUE_TYPES.get(value_type)
        if codec is None:
            raise ScanError(f"Unsupported value type: {value_type}")
        normalized = _normalize_mode(mode)
        if normalized not in {"unknown", "exact", "between"}:
            raise ScanError(f"{mode} requires a prior scan; start with unknown, exact, or between")
        if stride <= 0:
            raise ScanError("Scan stride must be positive")
        possible = 0 if len(snapshot.data) < codec.size else ((len(snapshot.data) - codec.size) // stride) + 1
        if possible > self.max_candidates:
            raise ScanError(
                f"Scan would create {possible:,} candidates; limit is {self.max_candidates:,}. "
                "Increase stride or scan a smaller snapshot."
            )
        self.value_type = codec
        self.stride = stride
        self.snapshot = snapshot
        self.previous_snapshot = None
        candidates: list[int] = []
        for offset in range(0, len(snapshot.data) - codec.size + 1, stride):
            current = codec.decode(snapshot.data, offset)
            if self._matches_initial(normalized, current, value, second):
                candidates.append(snapshot.base_address + offset)
        self.candidates = candidates
        return len(candidates)

    @staticmethod
    def _matches_initial(
        mode: str,
        current: int | float,
        value: int | float | None,
        second: int | float | None,
    ) -> bool:
        if mode == "unknown":
            return True
        if isinstance(current, float) and math.isnan(current):
            return False
        if mode == "exact":
            if value is None:
                raise ScanError("Exact scan requires a value")
            return current == value
        if value is None or second is None:
            raise ScanError("Between scan requires lower and upper values")
        lower, upper = sorted((value, second))
        return lower <= current <= upper

    def refine(
        self,
        snapshot: MemorySnapshot,
        mode: str,
        *,
        value: int | float | None = None,
        second: int | float | None = None,
        mask: int | None = None,
    ) -> int:
        if self.value_type is None or self.snapshot is None:
            raise ScanError("Start a scan before refining it")
        normalized = _normalize_mode(mode)
        if normalized == "unknown":
            raise ScanError("Unknown is only valid for an initial scan")
        codec = self.value_type
        if mask is not None and mask < 0:
            raise ScanError("Bit mask cannot be negative")
        retained: list[int] = []
        previous_snapshot = self.snapshot
        for address in self.candidates:
            if not previous_snapshot.contains(address, codec.size) or not snapshot.contains(address, codec.size):
                continue
            old_offset = address - previous_snapshot.base_address
            new_offset = address - snapshot.base_address
            previous = codec.decode(previous_snapshot.data, old_offset)
            current = codec.decode(snapshot.data, new_offset)
            previous_bits = codec.bits(previous_snapshot.data, old_offset)
            current_bits = codec.bits(snapshot.data, new_offset)
            if self._matches_refine(
                normalized,
                previous,
                current,
                previous_bits,
                current_bits,
                value,
                second,
                mask,
            ):
                retained.append(address)
        self.previous_snapshot = previous_snapshot
        self.snapshot = snapshot
        self.candidates = retained
        return len(retained)

    @staticmethod
    def _matches_refine(
        mode: str,
        previous: int | float,
        current: int | float,
        previous_bits: int,
        current_bits: int,
        value: int | float | None,
        second: int | float | None,
        mask: int | None,
    ) -> bool:
        if mode == "changed":
            return current_bits != previous_bits
        if mode == "unchanged":
            return current_bits == previous_bits
        if mode == "bit_changed":
            changed = current_bits ^ previous_bits
            return bool(changed if mask is None else changed & mask)
        if mode == "exact":
            if value is None:
                raise ScanError("Exact scan requires a value")
            return not (isinstance(current, float) and math.isnan(current)) and current == value
        if mode == "between":
            if value is None or second is None:
                raise ScanError("Between scan requires lower and upper values")
            if isinstance(current, float) and math.isnan(current):
                return False
            lower, upper = sorted((value, second))
            return lower <= current <= upper
        if isinstance(previous, float) and (math.isnan(previous) or math.isnan(float(current))):
            return False
        if mode == "increased":
            return current > previous
        if mode == "decreased":
            return current < previous
        if mode == "by":
            if value is None:
                raise ScanError("By scan requires a signed delta")
            return current - previous == value
        raise ScanError(f"Unsupported refinement mode: {mode}")

    def results(self, limit: int | None = None) -> list[ScanResult]:
        if self.value_type is None or self.snapshot is None:
            return []
        if limit is not None and limit < 0:
            raise ScanError("Result limit cannot be negative")
        addresses = self.candidates if limit is None else self.candidates[:limit]
        codec = self.value_type
        output: list[ScanResult] = []
        for address in addresses:
            current = codec.decode(self.snapshot.data, address - self.snapshot.base_address)
            previous: int | float | None = None
            if self.previous_snapshot and self.previous_snapshot.contains(address, codec.size):
                previous = codec.decode(
                    self.previous_snapshot.data, address - self.previous_snapshot.base_address
                )
            output.append(ScanResult(address, current, previous))
        return output

    def iter_results(self) -> Iterator[ScanResult]:
        yield from self.results()


def format_scan_value(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".9g")
    return str(value)
