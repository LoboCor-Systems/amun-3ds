"""Deterministic smoke mutator for Python source-profile and network boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys
import tempfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from compiler.profile import ProfileLoadError, load_profile, validate_profile
from hub.protocol import FrameDecoder, ProtocolError


def main() -> int:
    randomizer = random.Random(0x414D554E)
    with tempfile.TemporaryDirectory() as directory:
        profile = Path(directory) / "profile.json"
        for _ in range(1000):
            data = randomizer.randbytes(randomizer.randrange(0, 4097))
            profile.write_bytes(data)
            try:
                loaded = load_profile(profile)
                validate_profile(loaded.document)
            except (ProfileLoadError, UnicodeError, OSError, ValueError, json.JSONDecodeError):
                pass
            decoder = FrameDecoder()
            try:
                decoder.feed(data)
            except ProtocolError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
