#!/usr/bin/env python3
"""Capture a bounded, read-only memory range from Luma's GDB RSP server.

This fallback is intentionally smaller than a debugger: it can negotiate an RSP
session, attach to one process, read memory, and detach.  It implements no target
memory-write or execution-control command.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import socket
import sys


class RspError(RuntimeError):
    pass


def bounded_integer(text: str, *, minimum: int, maximum: int, label: str) -> int:
    try:
        value = int(text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from error
    if not minimum <= value <= maximum:
        raise argparse.ArgumentTypeError(
            f"{label} must be between {minimum:#x} and {maximum:#x}"
        )
    return value


class RspClient:
    def __init__(self, host: str, port: int, *, timeout: float = 8.0) -> None:
        self.socket = socket.create_connection((host, port), timeout=timeout)
        self.socket.settimeout(timeout)
        self.packet_size = 0x1000
        self.attached = False
        self.pid: int | None = None

    @staticmethod
    def _frame(payload: str) -> bytes:
        encoded = payload.encode("ascii")
        checksum = sum(encoded) & 0xFF
        return b"$" + encoded + f"#{checksum:02x}".encode("ascii")

    def _receive_byte(self) -> bytes:
        value = self.socket.recv(1)
        if not value:
            raise RspError("Luma closed the GDB connection")
        return value

    def _receive_packet(self, first: bytes) -> tuple[bytes, bytes]:
        encoded = bytearray()
        while True:
            value = self._receive_byte()
            if value == b"#":
                break
            encoded.extend(value)
        expected_text = self._receive_byte() + self._receive_byte()
        try:
            expected = int(expected_text, 16)
        except ValueError as error:
            raise RspError("Luma returned a malformed RSP checksum") from error
        actual = sum(encoded) & 0xFF
        if expected != actual:
            self.socket.sendall(b"-")
            raise RspError("Luma returned an RSP packet with a bad checksum")
        self.socket.sendall(b"+")
        return first, bytes(encoded)

    @staticmethod
    def _decode(encoded: bytes) -> bytes:
        decoded = bytearray()
        index = 0
        while index < len(encoded):
            value = encoded[index]
            if value == ord("}"):
                index += 1
                if index >= len(encoded):
                    raise RspError("Luma returned a truncated escaped RSP packet")
                decoded.append(encoded[index] ^ 0x20)
            elif value == ord("*"):
                index += 1
                if not decoded or index >= len(encoded):
                    raise RspError("Luma returned malformed RSP run-length data")
                repeat = encoded[index] - 29
                if repeat < 0:
                    raise RspError("Luma returned invalid RSP run-length data")
                decoded.extend([decoded[-1]] * repeat)
            else:
                decoded.append(value)
            index += 1
        return bytes(decoded)

    def command(self, payload: str) -> str:
        frame = self._frame(payload)
        for _attempt in range(3):
            self.socket.sendall(frame)
            while True:
                value = self._receive_byte()
                if value == b"+":
                    continue
                if value == b"-":
                    break
                if value not in (b"$", b"%"):
                    continue
                kind, encoded = self._receive_packet(value)
                if kind == b"%":
                    continue
                try:
                    return self._decode(encoded).decode("ascii")
                except UnicodeDecodeError as error:
                    raise RspError("Luma returned a non-ASCII RSP result") from error
        raise RspError(f"Luma repeatedly rejected the RSP packet: {payload}")

    def negotiate(self) -> None:
        supported = self.command(
            "qSupported:multiprocess+;swbreak+;hwbreak+;vContSupported+"
        )
        for item in supported.split(";"):
            if item.startswith("PacketSize="):
                try:
                    self.packet_size = int(item.partition("=")[2], 16)
                except ValueError:
                    pass
        result = self.command("!")
        if result not in ("", "OK"):
            raise RspError(f"Luma rejected extended mode: {result}")

    def attach(self, pid: int) -> None:
        result = self.command(f"vAttach;{pid:x}")
        if not result.startswith(("S", "T")):
            raise RspError(f"Luma could not attach to PID {pid}: {result}")
        self.attached = True
        self.pid = pid

    def read_memory(self, address: int, size: int) -> bytes:
        # A memory reply hex-encodes every byte and must fit in PacketSize.
        chunk_limit = max(1, min(0x4000, (self.packet_size - 4) // 2))
        output = bytearray()
        while len(output) < size:
            count = min(chunk_limit, size - len(output))
            current = address + len(output)
            result = self.command(f"m{current:x},{count:x}")
            if result.startswith("E"):
                raise RspError(f"Luma rejected memory read at {current:#010x}: {result}")
            try:
                chunk = bytes.fromhex(result)
            except ValueError as error:
                raise RspError(f"Luma returned malformed memory at {current:#010x}") from error
            if len(chunk) != count:
                raise RspError(
                    f"Luma returned {len(chunk)} bytes at {current:#010x}; expected {count}"
                )
            output.extend(chunk)
        return bytes(output)

    def detach(self) -> None:
        if not self.attached:
            return
        if self.pid is None:
            raise RspError("attached RSP session has no process ID")
        result = self.command(f"D;{self.pid:x}")
        self.attached = False
        self.pid = None
        if result not in ("", "OK"):
            raise RspError(f"Luma rejected detach: {result}")

    def close(self) -> None:
        try:
            self.detach()
        finally:
            self.socket.close()

    def __enter__(self) -> "RspClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument(
        "--port", type=lambda value: bounded_integer(value, minimum=1, maximum=65535, label="port"), default=4000
    )
    parser.add_argument(
        "--pid", required=True, type=lambda value: bounded_integer(value, minimum=1, maximum=0xFFFFFFFF, label="PID")
    )
    parser.add_argument(
        "--address", required=True, type=lambda value: bounded_integer(value, minimum=0, maximum=0xFFFFFFFF, label="address")
    )
    parser.add_argument(
        "--size", required=True, type=lambda value: bounded_integer(value, minimum=1, maximum=16 * 1024 * 1024, label="size")
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args()

    if arguments.address + arguments.size > 0x100000000:
        parser.error("address plus size exceeds the 32-bit address space")
    output = arguments.output.resolve()
    if output.exists() and not arguments.force:
        parser.error(f"output already exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with RspClient(arguments.host, arguments.port) as client:
            client.negotiate()
            client.attach(arguments.pid)
            data = client.read_memory(arguments.address, arguments.size)
            client.detach()
    except (OSError, RspError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    output.write_bytes(data)
    print(f"captured {len(data)} bytes from {arguments.address:#010x} to {output}")
    print(f"sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
