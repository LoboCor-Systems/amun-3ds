from __future__ import annotations

import socket
import sys
import threading
import unittest
from unittest.mock import patch

from studio.live import (
    GdbMiClient,
    LiveError,
    LiveWatch,
    LumaRspClient,
    ProcessInfo,
    WatchSymbol,
    suggest_process,
)


class LiveGdbTests(unittest.TestCase):
    def test_rsp_no_ack_negotiation_buffering_and_reconnect(self) -> None:
        class FakeSocket:
            def __init__(self, no_ack: bool) -> None:
                self.no_ack = no_ack
                self.pending = bytearray()
                self.sent: list[bytes] = []
                self.closed = False

            def settimeout(self, _timeout: float) -> None:
                pass

            def setsockopt(self, *_args: int) -> None:
                pass

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)
                if not data.startswith(b"$"):
                    return
                payload = data[1:data.index(b"#")].decode("ascii")
                if payload.startswith("qSupported"):
                    response = "PacketSize=800;QStartNoAckMode+" if self.no_ack else ""
                elif payload == "QStartNoAckMode" or payload == "!" or payload == "D;27":
                    response = "OK"
                elif payload == "vAttach;27":
                    response = "T05thread:p27.1;"
                elif payload == "m1413c540,4":
                    response = "1e000000"
                else:
                    raise AssertionError(payload)
                self.pending.extend(b"+" + LumaRspClient._frame(response))

            def recv(self, size: int) -> bytes:
                if size != 4096:
                    raise AssertionError("transport regressed to byte-at-a-time socket reads")
                chunk = bytes(self.pending[:7])  # split payloads and checksums across receives
                del self.pending[:7]
                return chunk

            def close(self) -> None:
                self.closed = True

        first, second = FakeSocket(True), FakeSocket(False)
        client = LumaRspClient()
        with patch("studio.live.socket.create_connection", side_effect=[first, second]):
            client.connect("127.0.0.1")
            self.assertTrue(client._no_ack)
            client.attach(39)
            self.assertEqual(client.read_memory(0x1413C540, 4), b"\x1e\0\0\0")
            client.close()
            # qSupported and QStartNoAckMode OK get the final normal-mode ACKs.
            self.assertEqual(first.sent.count(b"+"), 2)
            self.assertTrue(first.closed)
            self.assertEqual(client._receive_buffer, b"")
            client.connect("127.0.0.1")
            self.assertFalse(client._no_ack)
            self.assertEqual(client.packet_size, 0x400)
            client.close()
            self.assertEqual(second.sent.count(b"+"), 2)

    def client(self) -> GdbMiClient:
        return GdbMiClient((sys.executable, "-u", "-m", "studio.tests.fake_gdb"), timeout=2)

    def test_connect_processes_attach_and_read_are_read_only(self) -> None:
        with self.client() as client:
            client.connect("127.0.0.1")
            processes = client.list_processes()
            self.assertEqual(processes[0].pid, 42)
            client.attach(42)
            self.assertEqual(client.read_memory(0x08000000, 4), b"\x01\x02\x03\x04")
            self.assertFalse(hasattr(client, "write_memory"))

    def test_live_watch_tracks_previous_little_endian_values(self) -> None:
        with self.client() as client:
            client.connect("127.0.0.1")
            client.attach(42)
            watch = LiveWatch(client, [WatchSymbol("player.hp", 0x08000000, "u16")])
            first = watch.sample()[0]
            second = watch.sample()[0]
            self.assertIsNone(first.previous)
            self.assertEqual(first.current, 0x0201)
            self.assertEqual(second.previous, 0x0201)

    def test_address_and_read_size_are_bounded(self) -> None:
        with self.client() as client:
            with self.assertRaises(LiveError):
                client.read_memory(0xFFFFFFFF, 2)
            with self.assertRaises(LiveError):
                client.connect("bad host")

    def test_native_rsp_process_xml_supplies_exact_attach_pid(self) -> None:
        client = object.__new__(LumaRspClient)
        client.packet_size = 0x400
        client.attached = False
        client.pid = None
        client.attached_pid = None
        xml = (
            '<osdata type="processes">'
            '<item><column name="pid">7</column><column name="command">menu</column></item>'
            '<item><column name="pid">41</column><column name="command">Kart7</column></item>'
            '</osdata>'
        )
        commands: list[str] = []

        def command(payload: str) -> str:
            commands.append(payload)
            if payload.startswith("qXfer:osdata:read:processes:"):
                return "l" + xml
            if payload.startswith("vAttach;"):
                return "T05thread:p29.1;"
            if payload.startswith("D;"):
                return "OK"
            raise AssertionError(payload)

        client.command = command  # type: ignore[method-assign]
        processes = client.list_processes()
        self.assertEqual(processes, [ProcessInfo(7, "menu"), ProcessInfo(41, "Kart7")])

        client.attach(processes[1].pid)
        self.assertEqual(client.attached_pid, 41)
        client.detach()

        self.assertIn("vAttach;29", commands)
        self.assertIn("D;29", commands)
        self.assertFalse(hasattr(LumaRspClient, "write_memory"))

    def test_process_suggestion_uses_profile_name_but_never_attaches(self) -> None:
        processes = [ProcessInfo(55, "menu"), ProcessInfo(41, "Kart7")]
        suggestion = suggest_process(processes, ("Mario Kart 7", "0004000000030700"))
        self.assertIsNotNone(suggestion)
        assert suggestion is not None
        self.assertEqual(suggestion.process.pid, 41)
        self.assertEqual(suggestion.reason, "profile-name match")

    def test_native_rsp_connect_list_attach_read_and_detach(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        errors: list[BaseException] = []
        commands: list[str] = []
        xml = (
            '<osdata type="processes"><item><column name="pid">41</column>'
            '<column name="command">Kart7</column></item></osdata>'
        )

        def frame(payload: str) -> bytes:
            encoded = payload.encode("ascii")
            return b"$" + encoded + f"#{sum(encoded) & 0xFF:02x}".encode("ascii")

        def receive(connection: socket.socket) -> str:
            while connection.recv(1) != b"$":
                pass
            payload = bytearray()
            while True:
                value = connection.recv(1)
                if value == b"#":
                    break
                payload.extend(value)
            connection.recv(2)
            return payload.decode("ascii")

        def serve() -> None:
            try:
                connection, _address = listener.accept()
                with connection:
                    while True:
                        command = receive(connection)
                        commands.append(command)
                        if command.startswith("qSupported"):
                            response = "PacketSize=400;qXfer:osdata:read+"
                        elif command == "!":
                            response = "OK"
                        elif command.startswith("qXfer:osdata:read:processes:"):
                            response = "l" + xml
                        elif command == "vAttach;29":
                            response = "T05thread:p29.1;"
                        elif command == "m8000000,4":
                            response = "01020304"
                        elif command == "D;29":
                            response = "OK"
                        else:
                            raise AssertionError(command)
                        connection.sendall(b"+" + frame(response))
                        connection.recv(1)  # packet acknowledgement
                        if command == "D;29":
                            break
            except BaseException as error:
                errors.append(error)
            finally:
                listener.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        with LumaRspClient("127.0.0.1", port, timeout=2) as client:
            self.assertEqual(client.list_processes(), [ProcessInfo(41, "Kart7")])
            client.attach(41)
            self.assertEqual(client.read_memory(0x08000000, 4), b"\x01\x02\x03\x04")
            client.detach()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIn("vAttach;29", commands)


if __name__ == "__main__":
    unittest.main()
