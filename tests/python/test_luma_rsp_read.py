import unittest

from scripts.luma_rsp_read import RspClient


class LumaRspReadTests(unittest.TestCase):
    def test_packet_frame_has_remote_checksum(self) -> None:
        self.assertEqual(RspClient._frame("m1413c540,4"), b"$m1413c540,4#92")

    def test_decoder_handles_escaping_and_run_length(self) -> None:
        self.assertEqual(RspClient._decode(b"A}\x04B"), b"A$B")
        self.assertEqual(RspClient._decode(b"0* "), b"0000")

    def test_detach_is_pid_qualified_and_no_write_api_exists(self) -> None:
        client = object.__new__(RspClient)
        client.attached = True
        client.pid = 41
        commands: list[str] = []
        client.command = lambda payload: commands.append(payload) or "OK"  # type: ignore[method-assign]

        client.detach()

        self.assertEqual(commands, ["D;29"])
        self.assertFalse(hasattr(RspClient, "write_memory"))


if __name__ == "__main__":
    unittest.main()
