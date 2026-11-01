"""Derive the MK7 EUR *stable* profile from the research progression profile.

The stable set is the part of the full set whose memory layout is hardware-confirmed on
EUR 3152: the five coin goals and the 13 cup/trophy/star goals (see
profiles/mario-kart-7-eur-progression/RESEARCH.md). Everything that still depends on
unconfirmed race/ghost live fields stays in the progression profile as the experimental set.

The stable profile is a pure subset: same IDs, triggers, points and symbol definitions, minus
the experimental goals, the symbols only they use, and the embedded scenarios that expect
them. Run this after editing the progression profile; a test fails if the committed stable
profile is stale.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "profiles" / "mario-kart-7-eur-progression" / "profile.json"
DEFAULT_OUT = ROOT / "profiles" / "mario-kart-7-eur" / "profile.json"

STABLE_IDS = (
    # coins (shipped and accepted earlier)
    "pocket_change", "coins_25", "coins_100", "coins_500", "coins_1000",
    # cup progression (cup table layout and bitfield hardware-confirmed 2026-09-22)
    "first_gp_gold", "gold_50_all", "gold_100_all",
    "gold_150_mushroom", "gold_150_flower", "gold_150_star", "gold_150_special",
    "gold_150_shell", "gold_150_banana", "gold_150_leaf", "gold_150_lightning",
    "gold_mirror_all", "star_150_all",
)

VERSION = "1.0.0-stable"
PROVENANCE = (
    "Original AMUN MK7 EUR stable set: coin and cup/trophy/star goals only. EUR effective "
    "version 3152 only; fingerprint live-text-crc32-v1:004EC000:2BE03E4B. Cup-major "
    "[cup*4+class] ordering and the gold/star bitfield decode were hardware-confirmed on an "
    "original 2DS (2026-09-22). Race, ghost and Time Trial goals are in the separate "
    "experimental set. Not an official or third-party achievement set."
)


def symbols_in(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "symbol" and isinstance(value, str):
                found.add(value)
            else:
                found |= symbols_in(value)
    elif isinstance(node, list):
        for item in node:
            found |= symbols_in(item)
    return found


def build() -> dict:
    profile = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in profile["achievements"]}
    missing = [i for i in STABLE_IDS if i not in by_id]
    if missing:
        raise SystemExit(f"stable ids missing from the progression profile: {missing}")

    achievements = [a for a in profile["achievements"] if a["id"] in STABLE_IDS]
    for a in achievements:
        a["tags"] = [t for t in a.get("tags", []) if t not in ("research-candidate",)]
        if "stable" not in a["tags"]:
            a["tags"].append("stable")

    # Keep every symbol the kept achievements use, plus anything those symbols derive from.
    wanted: set[str] = set()
    for a in achievements:
        wanted |= symbols_in(a)
    all_symbols = profile["symbols"]
    changed = True
    while changed:
        changed = False
        for name in sorted(wanted):
            extra = symbols_in(all_symbols[name]) - wanted
            if extra:
                wanted |= extra
                changed = True
    profile["symbols"] = {n: s for n, s in all_symbols.items() if n in wanted}
    profile["achievements"] = achievements

    kept = set(STABLE_IDS)
    scenarios = []
    for test in profile["tests"]:
        if not set(test["expectUnlocked"]) <= kept:
            continue
        if "expectLocked" in test:
            test["expectLocked"] = [i for i in test["expectLocked"] if i in kept]
        for frame in test["frames"]:
            frame["values"] = {k: v for k, v in frame["values"].items() if k in wanted}
        scenarios.append(test)
    profile["tests"] = scenarios

    profile["profile"]["version"] = VERSION
    profile["profile"]["provenance"] = PROVENANCE
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
