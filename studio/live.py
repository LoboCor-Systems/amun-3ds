"""Read-only native Luma RSP and optional GDB/MI Studio backends."""

from __future__ import annotations

from dataclasses import dataclass
import json
import queue
import re
import socket
import subprocess
import threading
import time
from typing import Iterable, Protocol, Sequence
import xml.etree.ElementTree as ET

from .scanner import VALUE_TYPES, MemorySnapshot, ScanError


class LiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    description: str


@dataclass(frozen=True)
class WatchSymbol:
    name: str
    address: int
    value_type: str


@dataclass(frozen=True)
class WatchValue:
    symbol: WatchSymbol
    previous: int | float | None
    current: int | float


class LiveMemoryClient(Protocol):
    """Common read-only surface shared by the native and external-GDB backends."""

    attached_pid: int | None

    def connect(self, host: str, port: int = 4000) -> None: ...
    def list_processes(self) -> list[ProcessInfo]: ...
    def attach(self, pid: int) -> None: ...
    def detach(self) -> None: ...
    def read_memory(self, address: int, size: int) -> bytes: ...
    def capture_snapshot(self, address: int, size: int, name: str = "live") -> MemorySnapshot: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ProcessSuggestion:
    process: ProcessInfo
    reason: str


def suggest_process(processes: Iterable[ProcessInfo], hints: Iterable[str] = ()) -> ProcessSuggestion | None:
    """Choose a visible suggestion without ever attaching to a guessed process."""

    candidates = list(processes)
    if not candidates:
        return None
    tokens: set[str] = set()
    for hint in hints:
        tokens.update(
            token for token in re.findall(r"[a-z0-9]+", hint.lower())
            if len(token) >= 3 and token not in {"the", "game", "version", "edition"}
        )
    ranked: list[tuple[int, int, ProcessInfo]] = []
    for process in candidates:
        normalized = "".join(character for character in process.description.lower() if character.isalnum())
        score = sum(len(token) for token in tokens if token in normalized or normalized in token)
        ranked.append((score, process.pid, process))
    score, _pid, process = max(ranked, key=lambda item: (item[0], item[1]))
    reason = "profile-name match" if score else "highest PID fallback; verify the process name"
    return ProcessSuggestion(process, reason)


class LumaRspClient:
    """Dependency-free, read-only client for Luma's documented GDB RSP endpoint."""

    MAX_TRANSFER = 1024 * 1024
    MAX_PROCESS_XML = 64 * 1024

    def __init__(
        self,
        host: str | None = None,
        port: int = 4000,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.timeout = timeout
        self.socket: socket.socket | None = None
        self._receive_buffer = bytearray()
        self._no_ack = False
        self.packet_size = 0x400
        self.attached = False
        self.pid: int | None = None
        self.attached_pid: int | None = None
        if host is not None:
            self.connect(host, port)

    @staticmethod
    def _frame(payload: str) -> bytes:
        try:
            encoded = payload.encode("ascii")
        except UnicodeEncodeError as error:
            raise LiveError("RSP commands must be ASCII") from error
        checksum = sum(encoded) & 0xFF
        return b"$" + encoded + f"#{checksum:02x}".encode("ascii")

    @staticmethod
    def _decode(encoded: bytes) -> bytes:
        decoded = bytearray()
        index = 0
        while index < len(encoded):
            value = encoded[index]
            if value == ord("}"):
                index += 1
                if index >= len(encoded):
                    raise LiveError("Luma returned a truncated escaped RSP packet")
                decoded.append(encoded[index] ^ 0x20)
            elif value == ord("*"):
                index += 1
                if not decoded or index >= len(encoded):
                    raise LiveError("Luma returned malformed RSP run-length data")
                repeat = encoded[index] - 29
                if repeat < 0:
                    raise LiveError("Luma returned invalid RSP run-length data")
                decoded.extend([decoded[-1]] * repeat)
            else:
                decoded.append(value)
            index += 1
        return bytes(decoded)

    def _socket(self) -> socket.socket:
        if self.socket is None:
            raise LiveError("not connected to Luma")
        return self.socket

    def connect(self, host: str, port: int = 4000) -> None:
        if self.socket is not None:
            raise LiveError("already connected to Luma")
        if not host or any(character.isspace() for character in host) or not 1 <= port <= 65535:
            raise LiveError("invalid Luma host or port")
        self._receive_buffer.clear()
        self._no_ack = False
        self.packet_size = 0x400
        try:
            connection = socket.create_connection((host, port), timeout=self.timeout)
            connection.settimeout(self.timeout)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as error:
            raise LiveError(f"cannot connect to Luma at {host}:{port}: {error}") from error
        self.socket = connection
        try:
            self.negotiate()
        except BaseException:
            connection.close()
            self.socket = None
            self._receive_buffer.clear()
            self._no_ack = False
            raise

    def _receive_byte(self) -> bytes:
        if self._receive_buffer:
            value = bytes(self._receive_buffer[:1])
            del self._receive_buffer[:1]
            return value
        try:
            value = self._socket().recv(4096)
        except socket.timeout as error:
            raise LiveError("Luma RSP response timed out") from error
        except OSError as error:
            raise LiveError(f"Luma RSP receive failed: {error}") from error
        if not value:
            raise LiveError("Luma closed the debugger connection")
        self._receive_buffer.extend(value[1:])
        return value[:1]

    def _receive_packet(self, first: bytes) -> tuple[bytes, bytes]:
        encoded = bytearray()
        while True:
            value = self._receive_byte()
            if value == b"#":
                break
            encoded.extend(value)
            if len(encoded) > self.MAX_PROCESS_XML:
                raise LiveError("Luma returned an oversized RSP packet")
        expected_text = self._receive_byte() + self._receive_byte()
        try:
            expected = int(expected_text, 16)
        except ValueError as error:
            raise LiveError("Luma returned a malformed RSP checksum") from error
        actual = sum(encoded) & 0xFF
        if expected != actual:
            if not self._no_ack:
                self._socket().sendall(b"-")
            raise LiveError("Luma returned an RSP packet with a bad checksum")
        if not self._no_ack:
            self._socket().sendall(b"+")
        return first, bytes(encoded)

    def command(self, payload: str) -> str:
        frame = self._frame(payload)
        for _attempt in range(3):
            try:
                self._socket().sendall(frame)
            except OSError as error:
                raise LiveError(f"could not send an RSP command to Luma: {error}") from error
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
                    raise LiveError("Luma returned a non-ASCII RSP result") from error
        raise LiveError(f"Luma repeatedly rejected the RSP packet: {payload}")

    def negotiate(self) -> None:
        supported = self.command("qSupported:multiprocess+;swbreak+;hwbreak+;vContSupported+")
        if supported.startswith("E"):
            raise LiveError(f"Luma rejected RSP negotiation: {supported}")
        for item in supported.split(";"):
            if item.startswith("PacketSize="):
                try:
                    self.packet_size = max(64, int(item.partition("=")[2], 16))
                except ValueError:
                    pass
        if "QStartNoAckMode+" in supported.split(";"):
            # Acknowledging every memory packet separately adds delayed-ACK latency
            # on Windows/Wi-Fi. Negotiate the optional standard mode explicitly.
            if self.command("QStartNoAckMode") == "OK":
                self._no_ack = True
        result = self.command("!")
        if result not in ("", "OK"):
            raise LiveError(f"Luma rejected extended mode: {result}")

    def _read_xfer(self, object_name: str, annex: str) -> str:
        output: list[str] = []
        offset = 0
        chunk_size = max(1, min(0x300, self.packet_size - 32))
        while offset < self.MAX_PROCESS_XML:
            result = self.command(
                f"qXfer:{object_name}:read:{annex}:{offset:x},{chunk_size:x}"
            )
            if not result:
                raise LiveError(f"Luma does not provide {object_name}/{annex} data")
            marker, chunk = result[0], result[1:]
            if marker not in ("m", "l"):
                raise LiveError(f"Luma returned malformed {object_name}/{annex} data: {result[:32]}")
            output.append(chunk)
            offset += len(chunk.encode("ascii"))
            if marker == "l":
                return "".join(output)
            if not chunk:
                raise LiveError(f"Luma stalled while returning {object_name}/{annex} data")
        raise LiveError(f"Luma returned oversized {object_name}/{annex} data")

    def list_processes(self) -> list[ProcessInfo]:
        text = self._read_xfer("osdata", "processes")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as error:
            raise LiveError(f"Luma returned malformed process XML: {error}") from error
        if root.tag != "osdata" or root.attrib.get("type") != "processes":
            raise LiveError("Luma process response has the wrong XML type")
        processes: list[ProcessInfo] = []
        seen: set[int] = set()
        for item in root.findall("item"):
            columns = {
                str(column.attrib.get("name", "")): (column.text or "").strip()
                for column in item.findall("column")
            }
            try:
                pid = int(columns.get("pid", ""), 10)
            except ValueError:
                continue
            if not 1 <= pid <= 0xFFFFFFFF or pid in seen:
                continue
            seen.add(pid)
            processes.append(ProcessInfo(pid, columns.get("command", "") or "(unnamed)"))
        if not processes:
            raise LiveError("Luma returned no usable processes")
        return processes

    def attach(self, pid: int) -> None:
        if not 1 <= pid <= 0xFFFFFFFF:
            raise LiveError("invalid process ID")
        if self.attached:
            raise LiveError(f"already attached to PID {self.pid}")
        result = self.command(f"vAttach;{pid:x}")
        if not result.startswith(("S", "T")):
            raise LiveError(f"Luma could not attach to PID {pid}: {result}")
        self.attached = True
        self.pid = pid
        self.attached_pid = pid

    def read_memory(self, address: int, size: int) -> bytes:
        if not self.attached:
            raise LiveError("select and attach to a process before reading memory")
        if not 0 <= address <= 0xFFFFFFFF or not 1 <= size <= self.MAX_TRANSFER or address + size > 0x100000000:
            raise LiveError("read request is outside the bounded 3DS address space")
        chunk_limit = max(1, min(0x4000, (self.packet_size - 4) // 2))
        output = bytearray()
        while len(output) < size:
            count = min(chunk_limit, size - len(output))
            current = address + len(output)
            result = self.command(f"m{current:x},{count:x}")
            if result.startswith("E"):
                raise LiveError(f"Luma rejected memory read at {current:#010x}: {result}")
            try:
                chunk = bytes.fromhex(result)
            except ValueError as error:
                raise LiveError(f"Luma returned malformed memory at {current:#010x}") from error
            if len(chunk) != count:
                raise LiveError(f"Luma returned {len(chunk)} bytes at {current:#010x}; expected {count}")
            output.extend(chunk)
        return bytes(output)

    def capture_snapshot(self, address: int, size: int, name: str = "live") -> MemorySnapshot:
        return MemorySnapshot(self.read_memory(address, size), address, name, source="luma-rsp")

    def detach(self) -> None:
        if not self.attached:
            return
        if self.pid is None:
            raise LiveError("attached RSP session has no process ID")
        result = self.command(f"D;{self.pid:x}")
        self.attached = False
        self.pid = None
        self.attached_pid = None
        if result not in ("", "OK"):
            raise LiveError(f"Luma rejected detach: {result}")

    def close(self) -> None:
        connection, self.socket = self.socket, None
        if connection is None:
            return
        try:
            if self.attached:
                # Restore the socket while the detach command is in flight.
                self.socket = connection
                self.detach()
        finally:
            self.socket = None
            self._receive_buffer.clear()
            self._no_ack = False
            self.attached = False
            self.pid = None
            self.attached_pid = None
            connection.close()

    def __enter__(self) -> "LumaRspClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class GdbMiClient:
    """Minimal MI2 client. It intentionally exposes no memory-write operation."""

    def __init__(
        self,
        command: Sequence[str] = ("arm-none-eabi-gdb", "--interpreter=mi2", "--quiet"),
        *,
        timeout: float = 10.0,
    ) -> None:
        if not command:
            raise ValueError("GDB command cannot be empty")
        self.command = tuple(command)
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._token = 0
        self.attached_pid: int | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            raise LiveError(f"cannot launch GDB: {error}") from error
        self._reader_thread = threading.Thread(target=self._read_lines, daemon=True)
        self._reader_thread.start()

    def _read_lines(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line.rstrip("\r\n"))

    def command_mi(self, expression: str) -> tuple[str, list[str]]:
        self.start()
        assert self.process is not None and self.process.stdin is not None
        if self.process.poll() is not None:
            raise LiveError("GDB exited unexpectedly")
        self._token += 1
        token = self._token
        try:
            self.process.stdin.write(f"{token}{expression}\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise LiveError("could not send command to GDB") from error
        output: list[str] = []
        deadline = time.monotonic() + self.timeout
        prefix = f"{token}^"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LiveError(f"GDB command timed out: {expression}")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty as error:
                raise LiveError(f"GDB command timed out: {expression}") from error
            if line.startswith(prefix):
                result = line[len(prefix) :]
                if result.startswith("error"):
                    raise LiveError(f"GDB rejected command: {result}")
                if not (result.startswith("done") or result.startswith("connected") or result.startswith("exit")):
                    raise LiveError(f"unexpected GDB result: {result}")
                return result, output
            output.append(line)

    def connect(self, host: str, port: int = 4000) -> None:
        if not host or any(character.isspace() for character in host) or not 1 <= port <= 65535:
            raise LiveError("invalid GDB host or port")
        self.command_mi(f"-target-select extended-remote {host}:{port}")

    def console(self, expression: str) -> str:
        quoted = json.dumps(expression)
        _, records = self.command_mi(f"-interpreter-exec console {quoted}")
        pieces: list[str] = []
        for record in records:
            if record.startswith('~"'):
                try:
                    pieces.append(json.loads(record[1:]))
                except json.JSONDecodeError:
                    continue
        return "".join(pieces)

    def list_processes(self) -> list[ProcessInfo]:
        text = self.console("info os processes")
        processes: list[ProcessInfo] = []
        for line in text.splitlines():
            match = re.match(r"^\s*(?:process\s+)?(\d+)\s+(.+?)\s*$", line, re.IGNORECASE)
            if match:
                processes.append(ProcessInfo(int(match.group(1)), match.group(2)))
        return processes

    def attach(self, pid: int) -> None:
        if not 1 <= pid <= 0xFFFFFFFF:
            raise LiveError("invalid process ID")
        self.command_mi(f"-target-attach {pid}")
        self.attached_pid = pid

    def detach(self) -> None:
        if self.attached_pid is None:
            return
        self.command_mi("-target-detach")
        self.attached_pid = None

    def read_memory(self, address: int, size: int) -> bytes:
        if self.attached_pid is None:
            raise LiveError("select and attach to a process before reading memory")
        if not 0 <= address <= 0xFFFFFFFF or not 1 <= size <= 1024 * 1024 or address + size > 0x100000000:
            raise LiveError("read request is outside the bounded 3DS address space")
        result, _ = self.command_mi(f"-data-read-memory-bytes 0x{address:08X} {size}")
        match = re.search(r'contents="([0-9A-Fa-f]*)"', result)
        if match is None:
            raise LiveError("GDB response contains no memory bytes")
        try:
            data = bytes.fromhex(match.group(1))
        except ValueError as error:
            raise LiveError("GDB returned malformed hexadecimal memory") from error
        if len(data) != size:
            raise LiveError(f"GDB returned {len(data)} bytes; requested {size}")
        return data

    def capture_snapshot(self, address: int, size: int, name: str = "live") -> MemorySnapshot:
        return MemorySnapshot(self.read_memory(address, size), address, name, source="luma-gdb")

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(f"{self._token + 1}-gdb-exit\n")
                process.stdin.flush()
                process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        finally:
            self.attached_pid = None
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=1)
                self._reader_thread = None

    def __enter__(self) -> "GdbMiClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class LiveWatch:
    def __init__(self, client: LiveMemoryClient, symbols: Iterable[WatchSymbol]) -> None:
        self.client = client
        self.symbols = list(symbols)
        self._previous: dict[str, int | float] = {}
        names: set[str] = set()
        for symbol in self.symbols:
            if symbol.name in names or symbol.value_type not in VALUE_TYPES:
                raise ScanError(f"invalid or duplicate watch symbol: {symbol.name}")
            names.add(symbol.name)

    def sample(self) -> list[WatchValue]:
        values: list[WatchValue] = []
        for symbol in self.symbols:
            value_type = VALUE_TYPES[symbol.value_type]
            data = self.client.read_memory(symbol.address, value_type.size)
            current = value_type.decode(data, 0)
            values.append(WatchValue(symbol, self._previous.get(symbol.name), current))
            self._previous[symbol.name] = current
        return values
