"""Strict host-side inspection of AMUN trace files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
from typing import Any
import zlib


TRACE_HEADER = struct.Struct("<4sHHQ16sIHH")
FRAME_HEADER = struct.Struct("<4sIQHHI")
READ_HEADER = struct.Struct("<IHH")
MAX_TRACE_BYTES = 16 * 1024 * 1024
MAX_FRAMES = 1_000_000
MAX_READS_PER_FRAME = 2048
MAX_READ_BYTES = 4096


class TraceError(ValueError):
    pass


def inspect_trace(
    source: bytes | bytearray | memoryview | str | os.PathLike[str],
    *,
    include_frames: bool = False,
) -> dict[str, Any]:
    if isinstance(source, (str, os.PathLike)):
        path = Path(source).expanduser().resolve()
        try:
            if not TRACE_HEADER.size <= path.stat().st_size <= MAX_TRACE_BYTES:
                raise TraceError("trace file size is invalid")
            data = path.read_bytes()
        except OSError as error:
            raise TraceError(f"cannot read trace {path}: {error}") from error
    else:
        data = bytes(source)
    if not TRACE_HEADER.size <= len(data) <= MAX_TRACE_BYTES:
        raise TraceError("trace file size is invalid")
    magic, major, minor, title_id, profile_hash, frame_count, build_length, reserved = TRACE_HEADER.unpack_from(data)
    if magic != b"AMTR" or major != 1 or minor > 0:
        raise TraceError("invalid trace magic or version")
    if frame_count > MAX_FRAMES or build_length > 256 or TRACE_HEADER.size + build_length > len(data):
        raise TraceError("invalid trace header limits")
    try:
        build_id = data[TRACE_HEADER.size : TRACE_HEADER.size + build_length].decode("utf-8")
    except UnicodeDecodeError as error:
        raise TraceError("trace build id is not valid UTF-8") from error
    cursor = TRACE_HEADER.size + build_length
    frames: list[dict[str, Any]] = []
    total_reads = 0
    total_read_bytes = 0
    first_time: int | None = None
    last_time: int | None = None
    addresses: set[int] = set()
    for frame_index in range(frame_count):
        if cursor + FRAME_HEADER.size > len(data):
            raise TraceError(f"truncated trace frame header at frame {frame_index}")
        frame_magic, payload_size, monotonic_ms, read_count, frame_reserved, expected_crc = FRAME_HEADER.unpack_from(data, cursor)
        if frame_magic != b"FRAM" or read_count > MAX_READS_PER_FRAME:
            raise TraceError(f"invalid trace frame header at frame {frame_index}")
        payload_at = cursor + FRAME_HEADER.size
        payload_end = payload_at + payload_size
        if payload_end > len(data):
            raise TraceError(f"truncated payload at frame {frame_index}")
        payload = data[payload_at:payload_end]
        if zlib.crc32(payload) & 0xFFFFFFFF != expected_crc:
            raise TraceError(f"frame {frame_index} CRC-32 mismatch")
        payload_cursor = 0
        reads: list[dict[str, Any]] = []
        for read_index in range(read_count):
            if payload_cursor + READ_HEADER.size > len(payload):
                raise TraceError(f"truncated read {read_index} in frame {frame_index}")
            address, read_size, read_reserved = READ_HEADER.unpack_from(payload, payload_cursor)
            payload_cursor += READ_HEADER.size
            if not 1 <= read_size <= MAX_READ_BYTES or payload_cursor + read_size > len(payload):
                raise TraceError(f"invalid read {read_index} in frame {frame_index}")
            sample = payload[payload_cursor : payload_cursor + read_size]
            payload_cursor += read_size
            total_reads += 1
            total_read_bytes += read_size
            addresses.add(address)
            if include_frames:
                reads.append(
                    {
                        "address": f"0x{address:08X}",
                        "size": read_size,
                        "sha256": hashlib.sha256(sample).hexdigest(),
                        "bytes": sample.hex(),
                    }
                )
        if payload_cursor != len(payload):
            raise TraceError(f"frame {frame_index} has trailing payload")
        first_time = monotonic_ms if first_time is None else first_time
        last_time = monotonic_ms
        if include_frames:
            frames.append({"index": frame_index, "monotonicMs": monotonic_ms, "reads": reads})
        cursor = payload_end
    if cursor != len(data):
        raise TraceError("trace has trailing file data")
    result: dict[str, Any] = {
        "format": "AMTR",
        "version": f"{major}.{minor}",
        "titleId": f"{title_id:016X}",
        "profileHash": profile_hash.hex(),
        "buildId": build_id,
        "frameCount": frame_count,
        "readCount": total_reads,
        "readBytes": total_read_bytes,
        "uniqueReadAddresses": len(addresses),
        "firstMonotonicMs": first_time,
        "lastMonotonicMs": last_time,
        "reserved": reserved,
    }
    if include_frames:
        result["frames"] = frames
    return result
