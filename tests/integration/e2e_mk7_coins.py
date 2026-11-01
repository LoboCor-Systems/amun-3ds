"""Exercise the actual MK7 coin pack through the native VM and durable ledger.

These are synthetic traces, not claims of physical console unlock verification.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import struct
import tempfile
import zlib

from e2e_compiler_runtime import (
    FRAME_HEADER, READ_HEADER, REPOSITORY_ROOT, TRACE_HEADER, run_simulator,
)
from compiler.pack import compile_profile, write_pack
from compiler.profile import load_profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", type=Path, required=True)
    args = parser.parse_args()
    loaded = load_profile(REPOSITORY_ROOT / "profiles/mario-kart-7-eur-coins/profile.json")
    compiled = compile_profile(loaded)
    count = 0
    with tempfile.TemporaryDirectory(prefix="amun-mk7-e2e-") as temporary:
        root = Path(temporary)
        pack = write_pack(compiled, root / "game.amunpack")
        for build in loaded.document["game"]["builds"]:
            for index, scenario in enumerate(loaded.document["tests"]):
                build_id = build["id"].encode("ascii")
                frames = []
                for frame in scenario["frames"]:
                    value = frame["values"]["save.total_coins"]
                    payload = READ_HEADER.pack(0x1413C540, 4, 0) + struct.pack("<I", value)
                    frames.append(FRAME_HEADER.pack(b"FRAM", len(payload), frame["timeMs"],
                                  1, 0, zlib.crc32(payload) & 0xFFFFFFFF) + payload)
                data = TRACE_HEADER.pack(b"AMTR", 1, 0, 0x0004000000030700,
                        compiled.profile_hash, len(frames), len(build_id), 0) + build_id + b"".join(frames)
                trace = root / "synthetic.amuntrace"
                trace.write_bytes(data)
                ledger = root / f"{build['id']}-{index}.amunledger"
                first = run_simulator(args.simulator.resolve(), pack, trace, ledger)
                observed = set(re.findall(r"^UNLOCK (\S+)", first, re.MULTILINE))
                if observed != set(scenario["expectUnlocked"]):
                    raise AssertionError(f"{build['id']} / {scenario['name']}:\n{first}")
                second = run_simulator(args.simulator.resolve(), pack, trace, ledger)
                if re.search(r"^UNLOCK ", second, re.MULTILINE):
                    raise AssertionError(f"Restart duplicated an unlock:\n{second}")
                count += 1
    print(f"MK7 coin pack: {count} native scenarios + {count} persistent-ledger replays PASS")


if __name__ == "__main__":
    main()
