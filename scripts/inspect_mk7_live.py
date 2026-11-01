"""Read-only MK7 candidate evidence using Studio's native Luma backend.

Prints metadata, bounded candidate bytes and optionally a streamed text CRC.
Does not patch the process or save game executable bytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import struct
import sys
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.live import LiveError, LumaRspClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--text-size", type=lambda x: int(x, 0), default=0)
    args = parser.parse_args()
    if not 0 <= args.text_size <= 32 * 1024 * 1024:
        parser.error("text size must be 0..32 MiB")
    started = time.monotonic()
    with LumaRspClient(args.host, args.port, timeout=8) as client:
        client._socket().setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        processes = client.list_processes()
        chosen = next((p for p in processes if p.pid == args.pid), None)
        if chosen is None or not chosen.description.lower().startswith(("mario", "kart")):
            raise LiveError("the selected PID is not the named Mario Kart process")
        print(json.dumps({"pid": chosen.pid, "process": chosen.description}), flush=True)
        print("Luma: " + client._read_xfer("osdata", "cfwversion"), flush=True)
        client.attach(args.pid)
        try:
            coin_bytes = client.read_memory(0x1413C540, 4)
            header = client.read_memory(0x07000000, 0x100)
            values = struct.unpack_from("<6I", header)
            print(json.dumps({"coinAddress": "0x1413C540", "u32": int.from_bytes(coin_bytes, "little"),
                              "pluginHeader": [f"0x{x:08X}" for x in values]}), flush=True)
            memory_map = client.command("qRcmd," + b"getmemregions".hex())
            print("Memory map: " + bytes.fromhex(memory_map).decode("ascii"), flush=True)
            checksum = 0
            for offset in range(0, args.text_size, 32768):
                block = client.read_memory(0x00100000 + offset, min(32768, args.text_size - offset))
                checksum = zlib.crc32(block, checksum)
                if offset % (256 * 1024) == 0:
                    print(f"Fingerprint {offset}/{args.text_size} bytes", flush=True)
            if args.text_size:
                print(f"Fingerprint: live-text-crc32-v1:{args.text_size:08X}:{checksum:08X}", flush=True)
        finally:
            client.detach()
            print(f"Detached; game resumed. Elapsed {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
