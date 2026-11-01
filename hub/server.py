"""Async optional AMUN Hub with explicit six-digit LAN pairing."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import time
import uuid

from .metal_tiers import metal_name
from .protocol import Frame, FrameDecoder, MessageType, ProtocolError, encode_frame


@dataclass
class HubPaths:
    state: Path
    events: Path
    backups: Path


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.devices: dict[str, dict[str, str]] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.devices = {}
            return
        document = json.loads(self.path.read_text(encoding="utf-8"))
        devices = document.get("devices", {}) if isinstance(document, dict) else {}
        if not isinstance(devices, dict):
            raise ValueError("Hub state devices must be an object")
        self.devices = {
            str(key): {"name": str(value.get("name", "3DS")), "token": str(value["token"])}
            for key, value in devices.items()
            if isinstance(value, dict) and isinstance(value.get("token"), str)
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "devices": self.devices}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class HubServer:
    def __init__(
        self,
        paths: HubPaths,
        *,
        host: str = "0.0.0.0",
        port: int = 43831,
        pair_timeout: float = 60.0,
    ) -> None:
        self.paths = paths
        self.host = host
        self.port = port
        self.pair_timeout = pair_timeout
        self.state = StateStore(paths.state)
        self.state.load()
        self.server: asyncio.AbstractServer | None = None
        self._recent_ids: set[uuid.UUID] = set()
        self._recent_order: deque[uuid.UUID] = deque()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        socket = self.server.sockets[0]
        self.port = int(socket.getsockname()[1])

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def serve_forever(self) -> None:
        if self.server is None:
            await self.start()
        assert self.server is not None
        async with self.server:
            await self.server.serve_forever()

    async def _read_frame(self, reader: asyncio.StreamReader, timeout: float = 30.0) -> Frame:
        header = await asyncio.wait_for(reader.readexactly(32), timeout)
        length = int.from_bytes(header[8:12], "little")
        if length > 64 * 1024:
            raise ProtocolError("declared payload exceeds limit")
        body = await asyncio.wait_for(reader.readexactly(length), timeout)
        decoder = FrameDecoder()
        frames = decoder.feed(header + body)
        if len(frames) != 1:
            raise ProtocolError("expected exactly one frame")
        return frames[0]

    @staticmethod
    async def _send(
        writer: asyncio.StreamWriter,
        message_type: MessageType,
        payload: dict[str, object],
        *,
        message_id: uuid.UUID | None = None,
    ) -> None:
        writer.write(encode_frame(message_type, payload, message_id=message_id))
        await writer.drain()

    def _remember(self, identifier: uuid.UUID) -> bool:
        if identifier in self._recent_ids:
            return False
        self._recent_ids.add(identifier)
        self._recent_order.append(identifier)
        while len(self._recent_order) > 4096:
            expired = self._recent_order.popleft()
            self._recent_ids.discard(expired)
        return True

    async def _authenticate(
        self, hello: Frame, writer: asyncio.StreamWriter, reader: asyncio.StreamReader
    ) -> str | None:
        if hello.message_type is not MessageType.HELLO:
            raise ProtocolError("first message must be HELLO")
        device_id = hello.payload.get("device_id")
        name = hello.payload.get("name", "Nintendo 3DS")
        token = hello.payload.get("token", "")
        if not isinstance(device_id, str) or not (1 <= len(device_id) <= 128):
            raise ProtocolError("invalid device_id")
        known = self.state.devices.get(device_id)
        if known is not None and secrets.compare_digest(known["token"], str(token)):
            await self._send(writer, MessageType.HELLO_ACK, {"paired": True})
            return device_id

        code = f"{secrets.randbelow(1_000_000):06d}"
        print(f"Pairing request from {name} ({device_id}); code: {code}", flush=True)
        await self._send(
            writer,
            MessageType.PAIR_REQUIRED,
            {"code": code, "expires_seconds": int(self.pair_timeout)},
        )
        confirmation = await self._read_frame(reader, self.pair_timeout)
        supplied = confirmation.payload.get("code") if confirmation.message_type is MessageType.PAIR_CONFIRM else None
        if not isinstance(supplied, str) or not secrets.compare_digest(supplied, code):
            await self._send(writer, MessageType.ERROR, {"error": "pairing denied"})
            return None
        issued_token = secrets.token_hex(32)
        self.state.devices[device_id] = {"name": str(name)[:128], "token": issued_token}
        self.state.save()
        await self._send(writer, MessageType.PAIR_ACCEPTED, {"token": issued_token})
        return device_id

    def _append_event(self, device_id: str, frame: Frame) -> None:
        self.paths.events.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "received_unix_ms": int(time.time() * 1000),
            "device_id": device_id,
            "message_id": str(frame.message_id),
            "type": frame.message_type.name,
            "payload": frame.payload,
        }
        if frame.message_type is MessageType.UNLOCK:
            # Platform metal tier, derived from points at display time (docs/metal-tiers.md).
            # Stored beside the payload, never inside it, so the client's data stays verbatim.
            points = frame.payload.get("points")
            metal = metal_name(points)
            if metal is not None:
                record["metal"] = metal
            label = str(frame.payload.get("achievement_id", "?"))[:128]
            suffix = f" (+{points}, {metal})" if metal else (f" (+{points})" if isinstance(points, int) and not isinstance(points, bool) else "")
            print(f"Unlock from {device_id[:128]}: {label}{suffix}", flush=True)
        with self.paths.events.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()

    def _store_backup(self, device_id: str, frame: Frame) -> None:
        encoded = frame.payload.get("ledger_hex")
        if not isinstance(encoded, str) or len(encoded) > 2 * 1024 * 1024:
            raise ProtocolError("invalid bounded ledger backup")
        try:
            data = bytes.fromhex(encoded)
        except ValueError as error:
            raise ProtocolError("ledger backup is not hexadecimal") from error
        target_directory = self.paths.backups / "".join(c for c in device_id if c.isalnum() or c in "-_")
        target_directory.mkdir(parents=True, exist_ok=True)
        target = target_directory / f"{frame.message_id}.amunledger"
        target.write_bytes(data)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            hello = await self._read_frame(reader)
            device_id = await self._authenticate(hello, writer, reader)
            if device_id is None:
                return
            while True:
                frame = await self._read_frame(reader, 300.0)
                if frame.message_type is MessageType.PING:
                    await self._send(writer, MessageType.PONG, {}, message_id=frame.message_id)
                    continue
                if frame.message_type not in {
                    MessageType.UNLOCK,
                    MessageType.PROGRESS,
                    MessageType.LEDGER_BACKUP,
                }:
                    raise ProtocolError("message is not valid after authentication")
                fresh = self._remember(frame.message_id)
                if fresh:
                    if frame.message_type is MessageType.LEDGER_BACKUP:
                        self._store_backup(device_id, frame)
                    else:
                        self._append_event(device_id, frame)
                await self._send(
                    writer,
                    MessageType.ACK,
                    {"accepted": fresh, "duplicate": not fresh},
                    message_id=frame.message_id,
                )
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except (ProtocolError, asyncio.TimeoutError, ValueError, OSError) as error:
            try:
                await self._send(writer, MessageType.ERROR, {"error": str(error)[:512]})
            except (ConnectionError, OSError):
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

