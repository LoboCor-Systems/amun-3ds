"""Small, bounded, duplicate-addressable AMUN LAN protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import json
import struct
import uuid
import zlib


MAGIC = b"AMNP"
VERSION = 1
HEADER = struct.Struct("<4sBBHII16s")
MAX_PAYLOAD = 64 * 1024
MAX_BUFFER = MAX_PAYLOAD * 2


class ProtocolError(ValueError):
    pass


class MessageType(IntEnum):
    HELLO = 1
    HELLO_ACK = 2
    PAIR_REQUIRED = 3
    PAIR_CONFIRM = 4
    PAIR_ACCEPTED = 5
    UNLOCK = 6
    PROGRESS = 7
    LEDGER_BACKUP = 8
    PING = 9
    PONG = 10
    ACK = 11
    ERROR = 12


@dataclass(frozen=True)
class Frame:
    message_type: MessageType
    message_id: uuid.UUID
    payload: dict[str, object]
    flags: int = 0


def _reject_constant(value: str) -> None:
    raise ProtocolError(f"non-finite JSON number is forbidden: {value}")


def _decode_payload(raw: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"invalid UTF-8 JSON payload: {error}") from error
    if not isinstance(decoded, dict):
        raise ProtocolError("payload must be a JSON object")
    return decoded


def encode_frame(
    message_type: MessageType,
    payload: dict[str, object],
    *,
    message_id: uuid.UUID | None = None,
    flags: int = 0,
) -> bytes:
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be a dictionary")
    try:
        body = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProtocolError(f"payload is not canonical JSON: {error}") from error
    if len(body) > MAX_PAYLOAD:
        raise ProtocolError(f"payload exceeds {MAX_PAYLOAD} bytes")
    identifier = message_id or uuid.uuid4()
    header = HEADER.pack(
        MAGIC,
        VERSION,
        int(message_type),
        flags & 0xFFFF,
        len(body),
        zlib.crc32(body) & 0xFFFFFFFF,
        identifier.bytes,
    )
    return header + body


class FrameDecoder:
    def __init__(self, *, max_payload: int = MAX_PAYLOAD) -> None:
        if max_payload <= 0 or max_payload > MAX_PAYLOAD:
            raise ValueError("invalid decoder payload limit")
        self.max_payload = max_payload
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        if len(self._buffer) + len(data) > MAX_BUFFER:
            self._buffer.clear()
            raise ProtocolError("receive buffer limit exceeded")
        self._buffer.extend(data)
        frames: list[Frame] = []
        while len(self._buffer) >= HEADER.size:
            magic, version, raw_type, flags, length, expected_crc, raw_id = HEADER.unpack_from(
                self._buffer
            )
            if magic != MAGIC or version != VERSION:
                self._buffer.clear()
                raise ProtocolError("invalid protocol magic or version")
            try:
                message_type = MessageType(raw_type)
            except ValueError as error:
                self._buffer.clear()
                raise ProtocolError(f"unknown message type {raw_type}") from error
            if length > self.max_payload:
                self._buffer.clear()
                raise ProtocolError("declared payload exceeds limit")
            frame_size = HEADER.size + length
            if len(self._buffer) < frame_size:
                break
            body = bytes(self._buffer[HEADER.size:frame_size])
            del self._buffer[:frame_size]
            if zlib.crc32(body) & 0xFFFFFFFF != expected_crc:
                raise ProtocolError("payload CRC-32 mismatch")
            frames.append(Frame(message_type, uuid.UUID(bytes=raw_id), _decode_payload(body), flags))
        return frames

