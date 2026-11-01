"""Generate a valid, address-free AMUN hardware self-test profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Sequence


TITLE_ID = re.compile(r"^00040000[0-9A-Fa-f]{8}$")
LIVE_FINGERPRINT = re.compile(
    r"^live-text-crc32-v1:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})$"
)
PROBE_FINGERPRINT = "sha256:" + "0" * 64
REGIONS = ("JPN", "USA", "EUR", "AUS", "CHN", "KOR", "TWN")


def make_profile(
    title_id: str,
    region: str,
    application_version: str,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    title_id = title_id.upper()
    if TITLE_ID.fullmatch(title_id) is None:
        raise ValueError("title ID must be a full 16-hex native application ID beginning 00040000")
    if region not in REGIONS:
        raise ValueError("region must match the adapter: " + ", ".join(REGIONS))
    if not application_version.isdecimal() or not 0 <= int(application_version) <= 0xFFFF:
        raise ValueError("application version must be the decimal 0..65535 value shown by AMUN")
    if str(int(application_version)) != application_version:
        raise ValueError("application version must use the adapter's canonical decimal form")
    canonical_fingerprint = PROBE_FINGERPRINT
    stage = "probe"
    if fingerprint is not None:
        matched = LIVE_FINGERPRINT.fullmatch(fingerprint)
        if matched is None:
            raise ValueError(
                "fingerprint must be live-text-crc32-v1:<8 hex text size>:<8 hex CRC>"
            )
        if not 1 <= int(matched.group(1), 16) <= 32 * 1024 * 1024:
            raise ValueError("live-text fingerprint size must be within the adapter's 1..32 MiB bound")
        canonical_fingerprint = (
            f"live-text-crc32-v1:{matched.group(1).upper()}:{matched.group(2).upper()}"
        )
        stage = "exact"
    return {
        "schema": 1,
        "profile": {
            "version": f"1.0.0-hardware-self-test-{stage}",
            "license": "CC0-1.0",
            "authors": ["AMUN hardware self-test generator"],
            "provenance": (
                "Address-free generated profile for parser, identity, ledger, and toast testing."
            ),
            "integrity": "developer",
        },
        "game": {
            "platform": "3ds",
            "titleId": title_id,
            "name": "AMUN Hardware Self-Test Target",
            "builds": [
                {
                    "id": "hardware-self-test-build",
                    "region": region,
                    "applicationVersion": application_version,
                    "updateVersion": "",
                    "codeFingerprint": canonical_fingerprint,
                    "compatible": False,
                }
            ],
        },
        "symbols": {},
        "assets": {},
        "achievements": [
            {
                "id": "hardware_self_test",
                "title": "AMUN Hardware Self-Test",
                "description": "The exact-build runtime, ledger, and toast path remained active for one second without game-memory reads.",
                "points": 0,
                "author": "AMUN",
                "category": "misc",
                "tags": ["hardware-self-test", "address-free", "duration", stage],
                "secret": False,
                "missable": False,
                "prerequisites": [],
                "trigger": {
                    "op": "duration",
                    "milliseconds": 1000,
                    "condition": True,
                },
            }
        ],
        "tests": [
            {
                "name": "monotonic address-free unlock",
                "frames": [
                    {"timeMs": 0, "values": {}},
                    {"timeMs": 999, "values": {}},
                    {"timeMs": 1000, "values": {}},
                ],
                "expectUnlocked": ["hardware_self_test"],
            }
        ],
    }


def write_profile(document: dict[str, Any], destination: Path, *, force: bool = False) -> Path:
    destination = destination.expanduser().resolve()
    if destination.exists() and not force:
        raise ValueError(f"output already exists: {destination}; pass --force to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=destination.parent, delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title-id", required=True)
    parser.add_argument("--region", required=True, choices=REGIONS)
    parser.add_argument("--application-version", required=True)
    parser.add_argument(
        "--fingerprint",
        help="exact live-text-crc32-v1 string; omit for the guaranteed-nonmatching probe stage",
    )
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        document = make_profile(
            arguments.title_id,
            arguments.region,
            arguments.application_version,
            arguments.fingerprint,
        )
        output = write_profile(document, arguments.output, force=arguments.force)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
