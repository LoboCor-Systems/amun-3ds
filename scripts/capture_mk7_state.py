"""Bounded read-only MK7 EUR state capture for profile research.

Layout references: mk7re/MK7-Memory and mk7re/MK7-Emu-Scripts.
Does not import or execute their game-writing helpers. Always detaches on failure.
Captured data stays in the local ignored build directory; do not publish game data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.live import LiveError, LumaRspClient


def capture(client: LumaRspClient) -> dict:
    blocks = []
    pointers = {}
    result = {"capturedUtc": datetime.now(timezone.utc).isoformat(), "pointers": pointers, "blocks": blocks}

    def read(name: str, address: int, size: int) -> bytes:
        if not any(lo <= address and address + size <= hi for lo, hi in
                   ((0x00100000, 0x006BF000), (0x08000000, 0x08200000),
                    (0x14000000, 0x17801000))) or not 1 <= size <= 4096:
            raise LiveError(f"Invalid {name} candidate {address:#x}, size {size}")
        data = client.read_memory(address, size)
        blocks.append({"name": name, "address": f"0x{address:08X}", "hex": data.hex()})
        return data

    def ptr(name: str, address: int, xor: int = 0) -> int:
        value = int.from_bytes(read(name, address, 4), "little") ^ xor
        pointers[name] = f"0x{value:08X}"
        return value

    def engine(name: str, scene: int, kind: int) -> int:
        slot = scene + 0x1E4 + kind * 0xC
        if not read(name + ".exists", slot + 4, 1)[0]:
            raise LiveError(name + " not present in this scene")
        return ptr(name, slot, 0x75F1B26B)

    root = 0x006789B8
    root_scene = ptr("rootScene", root + 0x10)
    sequence = engine("sequence", root_scene, 4)
    menu = ptr("menu", sequence + 0xC0)
    menu_race = read("menu.raceInfo", menu + 0x74, 0x190)
    result["menuRace"] = dict(zip(("course", "playMode", "ruleMode", "type", "engine"),
                                       struct.unpack_from("<5I", menu_race, 0x160)))
    read("menu.gp", menu + 0x620, 0x108)
    system = engine("system", root_scene, 3)
    save_manager = ptr("saveManager", system + 0x28)
    # EUR v3152: the embedded save starts at C0, not the older template's B8.
    save = save_manager + 0xC0
    pointers["save"] = f"0x{save:08X}"
    result["coins"] = int.from_bytes(read("save.coins", save + 0x4C28, 4), "little")
    result["trophies"] = list(read("save.trophies", save + 0x70C, 32))
    shadow = ptr("saveShadow", save_manager + 0xB0)
    result["shadowCoins"] = int.from_bytes(read("shadow.coins", shadow + 0x4C28, 4), "little")
    result["shadowTrophies"] = list(read("shadow.trophies", shadow + 0x70C, 32))
    read("save.records", save + 0x100, 0x630)
    pad = ptr("padDirector", system + 0x3C)
    read("pad.flags", pad + 0x84, 3)
    scene_manager = ptr("sceneManager", root + 4)
    scene = ptr("scene", scene_manager + 4)
    try:
        character = engine("character", scene, 0)
        directors = ptr("directors", character + 0x1C)
        race = ptr("raceDirector", directors + 0x1C)
        mode = ptr("mode", race + 0x1BC)
        mode_data = read("mode.header", mode + 0x44, 0x1C8)
        result["raceState"] = mode_data[4]
        result["raceInfo"] = dict(zip(("course", "playMode", "ruleMode", "type", "engine"),
                                            struct.unpack_from("<5I", mode_data, 0x180)))
        read("mode.tail", mode + 0x4D8, 0x40)
        kart = ptr("kartDirector", directors + 0x10)
        unit_array = ptr("units", kart + 0x2C)
        unit = ptr("unit0", unit_array)
        vehicle = ptr("vehicle0", unit + 0x2C)
        read("vehicle.identity", vehicle + 0x84, 0x30)
        info = ptr("kartInfo0", vehicle + 0xB0)
        read("kartInfo0.data", info + 0x40, 0x34)
        read("vehicle.flags", vehicle + 0xC28, 0x14)
        lap = ptr("lap", mode + 0x504)
        read("lap.header", lap + 0x10, 0x20)
        lap_array = ptr("lapArray", lap + 0x2C)
        read("lap.player0", lap_array, 0x44)
        log = ptr("log", race + 0x1C0)
        read("log.header", log, 0x114)
        result["raceAvailable"] = True
    except LiveError as error:
        result["raceAvailable"] = False
        result["raceUnavailableReason"] = str(error)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a fresh capture name")
    with LumaRspClient(args.host, timeout=5) as client:
        matches = [p for p in client.list_processes() if p.description == "MarioKar"]
        if len(matches) != 1:
            raise LiveError("Expected exactly one MarioKar process")
        client.attach(matches[0].pid)
        try:
            result = capture(client)
        finally:
            client.detach()
            print("Detached; game resumed.", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "blocks"}, indent=2))
    print(f"Stored {len(result['blocks'])} bounded reads in {args.output}")


if __name__ == "__main__":
    main()
