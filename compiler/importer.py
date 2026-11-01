"""Conservative local importer for RA-style achievement JSON exports."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .profile import normalize_fingerprint


class ImportError(ValueError):
    pass


TYPE_MAP = {
    "8bit": "u8", "u8": "u8", "byte": "u8",
    "16bit": "u16", "u16": "u16",
    "32bit": "u32", "u32": "u32",
    "s8": "s8", "s16": "s16", "s32": "s32",
}
OP_MAP = {"=": "eq", "==": "eq", "!=": "ne", ">": "gt", ">=": "ge", "<": "lt", "<=": "le"}


def _safe_id(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("_")
    if not text or not text[0].isalpha():
        text = "ra_" + text
    return text[:128]


def _simple_conditions(
    achievement: dict[str, Any], achievement_id: str, symbols: dict[str, Any], warnings: list[str]
) -> dict[str, Any] | None:
    raw = achievement.get("conditions")
    if not isinstance(raw, list) or not raw:
        return None
    compiled: list[dict[str, Any]] = []
    for index, condition in enumerate(raw):
        if not isinstance(condition, dict):
            return None
        try:
            address_raw = condition["address"]
            address = int(address_raw, 0) if isinstance(address_raw, str) else int(address_raw)
            value_type = TYPE_MAP[str(condition.get("type", "u8")).lower()]
            operation = OP_MAP[str(condition.get("operator", "=="))]
            value = condition["value"]
        except (KeyError, TypeError, ValueError):
            return None
        symbol = f"ra.{achievement_id}.{index}"
        symbols[symbol] = {
            "type": value_type,
            "poll": "normal",
            "resolver": {"kind": "absolute", "address": f"0x{address:08X}"},
        }
        compiled.append({"op": operation, "symbol": symbol, "value": value})
    warnings.append(
        f"{achievement_id}: imported simple absolute-address conditions; verify every address/build manually"
    )
    return compiled[0] if len(compiled) == 1 else {"all": compiled}


def import_ra_document(source: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    raw_achievements = source.get("achievements", source.get("Achievements"))
    if not isinstance(raw_achievements, list):
        raise ImportError("RA export must contain an achievements array")
    warnings = [
        "Import used local JSON only; no RetroAchievements server, badges, hashes, or game metadata were queried.",
        "RA condition syntax is not equivalent to AMUN VM semantics. Every imported trigger requires review and trace testing.",
    ]
    title_id = str(source.get("titleId", "0004000000000000"))
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", title_id):
        warnings.append("Source had no valid 3DS Title ID; placeholder 0004000000000000 was used.")
        title_id = "0004000000000000"
    fingerprint = source.get("codeFingerprint")
    normalized_fingerprint = normalize_fingerprint(fingerprint)
    if normalized_fingerprint is None:
        warnings.append(
            "Source had no exact scheme-qualified executable fingerprint; a sha256: zero placeholder was used and must be replaced."
        )
        fingerprint = "sha256:" + "0" * 64
    else:
        fingerprint = normalized_fingerprint
    symbols: dict[str, Any] = {}
    achievements: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_achievements):
        if not isinstance(raw, dict):
            warnings.append(f"Skipped non-object achievement at index {index}.")
            continue
        achievement_id = _safe_id(raw.get("id", raw.get("ID")), f"achievement_{index + 1}")
        trigger = _simple_conditions(raw, achievement_id, symbols, warnings)
        imported_raw = raw.get("MemAddr", raw.get("memaddr", raw.get("condition")))
        if trigger is None:
            # A deliberately false placeholder keeps the draft safe and makes the unresolved work visible.
            trigger = {"op": "eq", "left": {"const": 0}, "right": 1}
            warnings.append(
                f"{achievement_id}: unsupported RA condition {imported_raw!r}; emitted an always-false placeholder"
            )
        achievements.append(
            {
                "id": achievement_id,
                "title": str(raw.get("title", raw.get("Title", achievement_id))),
                "description": str(raw.get("description", raw.get("Description", "Imported achievement"))),
                "points": max(0, min(int(raw.get("points", raw.get("Points", 0)) or 0), 10000)),
                "author": str(raw.get("author", "RetroAchievements import")),
                "category": "misc",
                "tags": ["imported", "needs-review"],
                "secret": bool(raw.get("secret", False)),
                "missable": False,
                "prerequisites": [],
                "trigger": trigger,
                "imported": {"source": "ra-style-local-json", "rawCondition": imported_raw},
            }
        )
    document = {
        "schema": 1,
        "profile": {
            "version": "0.1.0-imported",
            "license": str(source.get("license", "")),
            "authors": ["Local RA-style importer"],
            "provenance": "Imported locally from an RA-style JSON export; manual verification required.",
            "integrity": "imported",
        },
        "game": {
            "platform": "3ds",
            "titleId": title_id.upper(),
            "name": str(source.get("game", source.get("title", "Imported game"))),
            "builds": [
                {
                    "id": "imported-build-needs-verification",
                    "region": str(source.get("region", "")),
                    "applicationVersion": str(source.get("applicationVersion", "")),
                    "updateVersion": str(source.get("updateVersion", "")),
                    "codeFingerprint": fingerprint,
                    "compatible": False,
                }
            ],
        },
        "symbols": symbols,
        "assets": {},
        "achievements": achievements,
        "tests": [],
    }
    return document, warnings


def import_ra_file(path: str | os.PathLike[str]) -> tuple[dict[str, Any], list[str]]:
    selected = Path(path).expanduser().resolve()
    try:
        source = json.loads(selected.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ImportError(f"cannot read local RA-style JSON {selected}: {error}") from error
    if not isinstance(source, dict):
        raise ImportError("RA-style JSON root must be an object")
    return import_ra_document(source)


def write_imported_profile(document: dict[str, Any], path: str | os.PathLike[str]) -> Path:
    destination = Path(path).expanduser().resolve()
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
