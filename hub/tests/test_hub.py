from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import uuid

import contextlib
import io

from hub.metal_tiers import metal_name
from hub.protocol import Frame, FrameDecoder, MessageType, ProtocolError, encode_frame
from hub.server import HubPaths, HubServer


class ProtocolTests(unittest.TestCase):
    def test_fragmented_and_concatenated_frames_round_trip(self) -> None:
        first_id = uuid.uuid4()
        first = encode_frame(MessageType.PING, {"value": 7}, message_id=first_id)
        second = encode_frame(MessageType.PROGRESS, {"current": 2, "target": 5})
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(first[:9]), [])
        frames = decoder.feed(first[9:] + second)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].message_id, first_id)
        self.assertEqual(frames[1].payload["target"], 5)

    def test_checksum_and_size_are_rejected(self) -> None:
        encoded = bytearray(encode_frame(MessageType.PING, {"x": 1}))
        encoded[-1] ^= 1
        with self.assertRaises(ProtocolError):
            FrameDecoder().feed(encoded)
        oversized = bytearray(encode_frame(MessageType.PING, {}))
        oversized[8:12] = (64 * 1024 + 1).to_bytes(4, "little")
        with self.assertRaises(ProtocolError):
            FrameDecoder().feed(oversized)

    def test_nonfinite_json_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            encode_frame(MessageType.PROGRESS, {"value": float("nan")})


class ServerTests(unittest.TestCase):
    def test_pair_reconnect_and_duplicate_event(self) -> None:
        async def scenario(root: Path) -> None:
            paths = HubPaths(root / "state.json", root / "events.jsonl", root / "backups")
            server = HubServer(paths, host="127.0.0.1", port=0, pair_timeout=2)
            await server.start()
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            writer.write(encode_frame(MessageType.HELLO, {"device_id": "old2ds-1", "name": "2DS"}))
            await writer.drain()
            required = await server._read_frame(reader)
            self.assertEqual(required.message_type, MessageType.PAIR_REQUIRED)
            writer.write(encode_frame(MessageType.PAIR_CONFIRM, {"code": required.payload["code"]}))
            await writer.drain()
            accepted = await server._read_frame(reader)
            token = str(accepted.payload["token"])
            event_id = uuid.uuid4()
            packet = encode_frame(MessageType.UNLOCK, {"achievement_id": "boss"}, message_id=event_id)
            writer.write(packet + packet)
            await writer.drain()
            first_ack = await server._read_frame(reader)
            second_ack = await server._read_frame(reader)
            self.assertTrue(first_ack.payload["accepted"])
            self.assertTrue(second_ack.payload["duplicate"])
            writer.close()
            await writer.wait_closed()

            reader2, writer2 = await asyncio.open_connection("127.0.0.1", server.port)
            writer2.write(
                encode_frame(
                    MessageType.HELLO,
                    {"device_id": "old2ds-1", "name": "2DS", "token": token},
                )
            )
            await writer2.drain()
            hello_ack = await server._read_frame(reader2)
            self.assertEqual(hello_ack.message_type, MessageType.HELLO_ACK)
            writer2.close()
            await writer2.wait_closed()
            await server.close()
            records = paths.events.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(records), 1)
            self.assertEqual(json.loads(records[0])["payload"]["achievement_id"], "boss")

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))


class MetalTierEventTests(unittest.TestCase):
    def test_metal_name_bands(self) -> None:
        self.assertIsNone(metal_name(0))
        self.assertIsNone(metal_name(True))
        self.assertIsNone(metal_name("10"))
        self.assertEqual(metal_name(4), "Copper")
        self.assertEqual(metal_name(10), "Silver")
        self.assertEqual(metal_name(25), "Gold")
        self.assertEqual(metal_name(100), "Rhodium")

    def test_unlock_record_carries_derived_metal_beside_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = HubServer(HubPaths(root / "s.json", root / "events.jsonl", root / "b"), port=0)
            ranked = Frame(MessageType.UNLOCK, uuid.uuid4(), {"achievement_id": "a", "points": 10})
            unranked = Frame(MessageType.UNLOCK, uuid.uuid4(), {"achievement_id": "b", "points": 0})
            progress = Frame(MessageType.PROGRESS, uuid.uuid4(), {"points": 50})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                for frame in (ranked, unranked, progress):
                    server._append_event("dev", frame)
            records = [json.loads(line) for line in (root / "events.jsonl").read_text("utf-8").splitlines()]
            self.assertEqual(records[0]["metal"], "Silver")
            self.assertEqual(records[0]["payload"], {"achievement_id": "a", "points": 10})
            self.assertNotIn("metal", records[1])
            self.assertNotIn("metal", records[2])
            self.assertIn("a (+10, Silver)", output.getvalue())


if __name__ == "__main__":
    unittest.main()

