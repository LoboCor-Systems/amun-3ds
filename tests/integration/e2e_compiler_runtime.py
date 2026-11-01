"""Compiler -> pack -> C++ runtime -> durable ledger integration test."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from compiler.pack import compile_profile, inspect_pack, write_pack
from compiler.profile import LoadedProfile


TRACE_HEADER = struct.Struct("<4sHHQ16sIHH")
FRAME_HEADER = struct.Struct("<4sIQHHI")
READ_HEADER = struct.Struct("<IHH")


def integration_profile(path: Path) -> LoadedProfile:
    document = {
        "schema": 1,
        "profile": {
            "version": "1.0.0",
            "license": "CC0-1.0",
            "authors": ["AMUN integration test"],
            "provenance": "Synthetic data generated during the host integration test.",
            "integrity": "developer",
        },
        "game": {
            "platform": "3ds",
            "titleId": "000400000FF40A00",
            "name": "AMUN Integration Target",
            "builds": [
                {
                    "id": "integration-v1",
                    "region": "EUR",
                    "applicationVersion": "1",
                    "updateVersion": "",
                    "codeFingerprint": "live-text-crc32-v1:00001000:2144DF1C",
                    "compatible": False,
                }
            ],
        },
        "symbols": {
            "synthetic.flag": {
                "type": "u8",
                "poll": "fast",
                "resolver": {"kind": "absolute", "address": "0x08001000"},
            }
        },
        "achievements": [
            {
                "id": "first_transition",
                "title": "First Transition",
                "description": "Observe a synthetic false-to-true transition.",
                "points": 5,
                "category": "test",
                "trigger": {
                    "op": "rising",
                    "condition": {
                        "op": "eq",
                        "left": {"symbol": "synthetic.flag"},
                        "right": 1,
                    },
                },
            }
        ],
    }
    return LoadedProfile(document, path, path.parent)


def trace_bytes(profile_hash: bytes) -> bytes:
    build = b"integration-v1"
    address = 0x08001000
    frames: list[bytes] = []
    for monotonic_ms, value in ((0, 0), (20, 1), (40, 1)):
        payload = READ_HEADER.pack(address, 1, 0) + bytes((value,))
        frames.append(
            FRAME_HEADER.pack(
                b"FRAM",
                len(payload),
                monotonic_ms,
                1,
                0,
                zlib.crc32(payload) & 0xFFFFFFFF,
            )
            + payload
        )
    return (
        TRACE_HEADER.pack(
            b"AMTR",
            1,
            0,
            0x000400000FF40A00,
            profile_hash,
            len(frames),
            len(build),
            0,
        )
        + build
        + b"".join(frames)
    )


def run_simulator(simulator: Path, pack: Path, trace: Path, ledger: Path) -> str:
    completed = subprocess.run(
        [str(simulator), "--pack", str(pack), "--trace", str(trace), "--ledger", str(ledger)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"simulator exited {completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", required=True, type=Path)
    arguments = parser.parse_args(argv)
    simulator = arguments.simulator.resolve()
    if not simulator.is_file():
        raise RuntimeError(f"simulator does not exist: {simulator}")

    with tempfile.TemporaryDirectory(prefix="amun-e2e-") as temporary:
        root = Path(temporary)
        compiled = compile_profile(integration_profile(root / "profile.json"))
        pack = write_pack(compiled, root / "game.amunpack")
        inspected = inspect_pack(pack)
        if inspected["manifest"]["titleId"] != "000400000FF40A00":
            raise RuntimeError("compiler pack inspector lost the full title ID")
        trace = root / "session.amuntrace"
        trace.write_bytes(trace_bytes(compiled.profile_hash))
        ledger = root / "persistent.amunledger"

        first = run_simulator(simulator, pack, trace, ledger)
        if "UNLOCK first_transition" not in first or "1 new unlocks" not in first:
            raise RuntimeError(f"first session did not produce the expected toast/unlock:\n{first}")
        if not ledger.is_file() or ledger.stat().st_size <= 8:
            raise RuntimeError("runtime did not create a durable ledger")

        second = run_simulator(simulator, pack, trace, ledger)
        if "UNLOCK first_transition" in second or "0 new unlocks" not in second:
            raise RuntimeError(f"restart duplicated an existing unlock:\n{second}")

    print("AMUN end-to-end integration: compiler, parser, VM, event, ledger, restart PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
