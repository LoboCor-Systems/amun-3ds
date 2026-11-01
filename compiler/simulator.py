"""Host-side execution of profile test scenarios using the core VM contract."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any

from .diagnostics import CompilationFailed, DiagnosticReport
from .pack import compile_profile
from .profile import LoadedProfile, ordered_symbol_names
from .vm import (
    BytecodeError,
    CompiledCondition,
    SymbolState,
    VmState,
    compile_condition,
    compile_expression,
    evaluate_bytecode,
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    failures: tuple[str, ...]
    unlocked: tuple[str, ...]
    progress: dict[str, int]
    frames: tuple[dict[str, Any], ...]


def _coerce_value(raw: Any, definition: dict[str, Any]) -> int | float | bytes:
    value_type = definition.get("type")
    if value_type == "f32":
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("f32 value must be finite")
        return struct.unpack("<f", struct.pack("<f", value))[0]
    if value_type in {"bytes", "fixed_string"}:
        size = int(definition["size"])
        if isinstance(raw, str):
            value = raw.encode("utf-8") if value_type == "fixed_string" else bytes.fromhex(raw)
        elif isinstance(raw, list):
            value = bytes(raw)
        elif isinstance(raw, bytes):
            value = raw
        else:
            raise ValueError(f"{value_type} test value must be text/hex or byte array")
        if len(value) > size:
            raise ValueError(f"{value_type} test value exceeds declared size {size}")
        return value.ljust(size, b"\0")
    value = int(raw)
    ranges = {
        "bit": (0, 1), "bool": (0, 1), "u8": (0, 255), "s8": (-128, 127),
        "u16": (0, 65535), "s16": (-32768, 32767),
        "u32": (0, 0xFFFFFFFF), "s32": (-0x80000000, 0x7FFFFFFF),
    }
    minimum, maximum = ranges[value_type]
    if not minimum <= value <= maximum:
        raise ValueError(f"value {value} is outside {value_type} range")
    return 1 if value_type == "bool" and value else value


def _update_snapshot(snapshot: SymbolState | None, value: int | float | bytes) -> SymbolState:
    if snapshot is None or not snapshot.valid:
        return SymbolState(value, value, value, False, True, True)
    return SymbolState(value, snapshot.current, snapshot.initial, True, snapshot.has_initial, True)


def run_profile_tests(
    loaded: LoadedProfile,
    *,
    scenario_name: str | None = None,
) -> list[ScenarioResult]:
    # Compilation runs all structural checks and independent bytecode verification.
    compile_profile(loaded)
    document = loaded.document
    symbol_names = ordered_symbol_names(document)
    definitions = document["symbols"]
    report = DiagnosticReport()
    derived: dict[int, CompiledCondition] = {}
    for index, name in enumerate(symbol_names):
        resolver = definitions[name]["resolver"]
        if resolver["kind"] == "derived":
            compiled = compile_expression(
                resolver["expression"], symbol_names, report, f"$.symbols.{name}.resolver.expression"
            )
            if compiled:
                derived[index] = compiled
    achievement_programs: list[CompiledCondition] = []
    for index, achievement in enumerate(document["achievements"]):
        compiled = compile_condition(
            achievement["trigger"], symbol_names, report, f"$.achievements[{index}].trigger"
        )
        if compiled:
            achievement_programs.append(compiled)
    if not report.ok or len(achievement_programs) != len(document["achievements"]):
        raise CompilationFailed(report)

    selected = [test for test in document.get("tests", []) if scenario_name is None or test.get("name") == scenario_name]
    if scenario_name is not None and not selected:
        raise ValueError(f"profile has no test scenario named {scenario_name!r}")
    results: list[ScenarioResult] = []
    for scenario in selected:
        snapshots: list[SymbolState | None] = [None] * len(symbol_names)
        vm_states = [VmState.with_slots(program.state_slots) for program in achievement_programs]
        unlocked: set[str] = set()
        progress: dict[str, int] = {}
        frame_results: list[dict[str, Any]] = []
        failures: list[str] = []
        for frame_index, frame in enumerate(scenario["frames"]):
            time_ms = int(frame.get("timeMs", frame_index * 100))
            values = frame["values"]
            for index, name in enumerate(symbol_names):
                if index in derived:
                    continue
                if name in values:
                    try:
                        snapshots[index] = _update_snapshot(
                            snapshots[index], _coerce_value(values[name], definitions[name])
                        )
                    except (ValueError, TypeError, OverflowError) as error:
                        failures.append(f"frame {frame_index} symbol {name}: {error}")
            for index, program in derived.items():
                materialized = [snapshot or SymbolState(0, valid=False) for snapshot in snapshots]
                try:
                    evaluated = evaluate_bytecode(
                        program.code,
                        materialized,
                        time_ms,
                        VmState.with_slots(0),
                        program.instructions,
                        max(program.maximum_stack, 1),
                    )
                    snapshots[index] = _update_snapshot(snapshots[index], evaluated.value)
                except BytecodeError as error:
                    failures.append(f"frame {frame_index} derived symbol {symbol_names[index]}: {error}")
            materialized = [snapshot or SymbolState(0, valid=False) for snapshot in snapshots]
            frame_unlocks: list[str] = []
            frame_progress: dict[str, int] = {}
            for achievement_index, achievement in enumerate(document["achievements"]):
                achievement_id = achievement["id"]
                if achievement_id in unlocked:
                    continue
                prereqs = achievement.get("prerequisites", [])
                if prereqs:
                    min_count = int(achievement.get("prerequisiteMinCount", 0) or 0)
                    required_count = len(prereqs) if min_count == 0 else min_count
                    met = sum(1 for required in prereqs if required in unlocked)
                    if met < required_count:
                        continue
                program = achievement_programs[achievement_index]
                try:
                    evaluated = evaluate_bytecode(
                        program.code,
                        materialized,
                        time_ms,
                        vm_states[achievement_index],
                        program.instructions,
                        max(program.maximum_stack, 1),
                    )
                except BytecodeError as error:
                    failures.append(f"frame {frame_index} achievement {achievement_id}: {error}")
                    continue
                if program.progress_target:
                    progress[achievement_id] = max(progress.get(achievement_id, 0), evaluated.progress)
                    frame_progress[achievement_id] = evaluated.progress
                if evaluated.condition:
                    unlocked.add(achievement_id)
                    frame_unlocks.append(achievement_id)
            frame_results.append(
                {"index": frame_index, "timeMs": time_ms, "unlocked": frame_unlocks, "progress": frame_progress}
            )
        expected_unlocked = set(scenario.get("expectUnlocked", []))
        if unlocked != expected_unlocked:
            failures.append(
                f"expected unlocked {sorted(expected_unlocked)}, observed {sorted(unlocked)}"
            )
        for achievement_id in scenario.get("expectLocked", []):
            if achievement_id in unlocked:
                failures.append(f"expected {achievement_id!r} to remain locked")
        for achievement_id, expected in scenario.get("expectProgress", {}).items():
            if progress.get(achievement_id, 0) != expected:
                failures.append(
                    f"expected progress {achievement_id}={expected}, observed {progress.get(achievement_id, 0)}"
                )
        results.append(
            ScenarioResult(
                str(scenario["name"]),
                not failures,
                tuple(failures),
                tuple(sorted(unlocked)),
                dict(sorted(progress.items())),
                tuple(frame_results),
            )
        )
    return results
