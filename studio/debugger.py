"""Condition debugger shared by Studio UI/tests and trace authoring workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from compiler.diagnostics import CompilationFailed, DiagnosticReport
from compiler.vm import (
    BytecodeError,
    CompiledCondition,
    EvalResult,
    SymbolState,
    VmState,
    compile_condition,
    disassemble,
    evaluate_bytecode,
)


@dataclass(frozen=True)
class DebugLine:
    path: str
    passed: bool | None
    text: str


@dataclass(frozen=True)
class DebugReport:
    condition: bool
    progress: int
    instructions: int
    lines: tuple[DebugLine, ...]
    disassembly: tuple[str, ...]


def _op(raw: Any) -> str:
    return str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")


class ConditionDebugger:
    def __init__(self, symbol_names: list[str], condition: Any, *, path: str = "trigger") -> None:
        self.symbol_names = list(symbol_names)
        self.condition_source = condition
        self.path = path
        report = DiagnosticReport()
        compiled = compile_condition(condition, symbol_names, report, path)
        if compiled is None or not report.ok:
            raise CompilationFailed(report)
        self.compiled: CompiledCondition = compiled
        self.state = VmState.with_slots(compiled.state_slots)
        self.symbols = [SymbolState(0, valid=False) for _ in symbol_names]

    def reset(self) -> None:
        self.state = VmState.with_slots(self.compiled.state_slots)
        self.symbols = [SymbolState(0, valid=False) for _ in self.symbol_names]

    def tick(self, current: Mapping[str, int | float | bytes], monotonic_ms: int) -> DebugReport:
        for index, name in enumerate(self.symbol_names):
            if name not in current:
                self.symbols[index].valid = False
                continue
            value = current[name]
            snapshot = self.symbols[index]
            if snapshot.valid:
                snapshot.previous = snapshot.current
                snapshot.has_previous = True
            else:
                snapshot.initial = value
                snapshot.previous = value
                snapshot.has_initial = True
                snapshot.has_previous = False
            snapshot.current = value
            snapshot.valid = True
        try:
            result = evaluate_bytecode(
                self.compiled.code,
                self.symbols,
                monotonic_ms,
                self.state,
                max(self.compiled.instructions, 1),
                max(self.compiled.maximum_stack, 1),
            )
        except BytecodeError as error:
            raise RuntimeError(f"condition evaluation failed: {error}") from error
        lines: list[DebugLine] = [
            DebugLine(self.path, result.condition, f"overall condition = {result.condition}")
        ]
        self._explain(self.condition_source, self.path, lines)
        for slot_index, slot in enumerate(self.state.slots):
            lines.append(
                DebugLine(
                    f"state[{slot_index}]",
                    None,
                    f"count={slot.count} stage={slot.stage} active={slot.active} "
                    f"latched={slot.latched} previous={slot.previous} "
                    f"started={slot.started_at} last={slot.last_at}",
                )
            )
        return DebugReport(
            result.condition,
            result.progress,
            result.instructions,
            tuple(lines),
            tuple(disassemble(self.compiled.code, self.symbol_names)),
        )

    def _symbol_value(self, raw: Any) -> tuple[Any, str]:
        if isinstance(raw, (int, float, bool, bytes)):
            return raw, repr(raw)
        if isinstance(raw, str):
            if raw in self.symbol_names:
                snapshot = self.symbols[self.symbol_names.index(raw)]
                return snapshot.current, f"{raw}={snapshot.current!r}"
            return raw, repr(raw)
        if not isinstance(raw, dict):
            return raw, repr(raw)
        if "symbol" in raw:
            name = str(raw["symbol"])
            if name not in self.symbol_names:
                return None, f"unknown {name}"
            snapshot = self.symbols[self.symbol_names.index(name)]
            state = str(raw.get("state", "current"))
            value = snapshot.current
            if state == "previous" and snapshot.has_previous:
                value = snapshot.previous
            elif state == "initial" and snapshot.has_initial:
                value = snapshot.initial
            return value, f"{name}.{state}={value!r}"
        if "const" in raw:
            return raw["const"], repr(raw["const"])
        if "value" in raw and len(raw) == 1:
            return raw["value"], repr(raw["value"])
        return raw, repr(raw)

    def _explain(self, raw: Any, path: str, lines: list[DebugLine]) -> bool | None:
        if isinstance(raw, bool):
            lines.append(DebugLine(path, raw, str(raw)))
            return raw
        if not isinstance(raw, dict):
            lines.append(DebugLine(path, None, "invalid source node"))
            return None
        if "all" in raw and "op" not in raw:
            raw = {"op": "all", "conditions": raw["all"]}
        elif "any" in raw and "op" not in raw:
            raw = {"op": "any", "conditions": raw["any"]}
        elif "not" in raw and "op" not in raw:
            raw = {"op": "not", "condition": raw["not"]}
        operation = _op(raw.get("op"))
        if operation in {"all", "any"}:
            children = [self._explain(child, f"{path}.conditions[{index}]", lines)
                        for index, child in enumerate(raw.get("conditions", []))]
            known = [value for value in children if value is not None]
            value = all(known) if operation == "all" and len(known) == len(children) else (
                any(known) if operation == "any" and len(known) == len(children) else None
            )
            lines.append(DebugLine(path, value, f"{operation.upper()} group"))
            return value
        if operation == "not":
            child = self._explain(raw.get("condition"), path + ".condition", lines)
            value = None if child is None else not child
            lines.append(DebugLine(path, value, "NOT"))
            return value
        aliases = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
        operation = aliases.get(operation, operation)
        if operation in {"eq", "ne", "lt", "le", "gt", "ge"}:
            left_source = raw.get("left", {"symbol": raw.get("symbol")})
            right_source = raw.get("right", raw.get("value"))
            left, left_text = self._symbol_value(left_source)
            right, right_text = self._symbol_value(right_source)
            try:
                if operation == "eq":
                    value = left == right
                elif operation == "ne":
                    value = left != right
                elif operation == "lt":
                    value = left < right
                elif operation == "le":
                    value = left <= right
                elif operation == "gt":
                    value = left > right
                else:
                    value = left >= right
            except TypeError:
                value = False
            lines.append(DebugLine(path, value, f"{left_text} {operation} {right_text}"))
            return value
        if operation in {"changed", "unchanged", "increased", "decreased"}:
            name = str(raw.get("symbol"))
            if name not in self.symbol_names:
                lines.append(DebugLine(path, False, f"unknown symbol {name}"))
                return False
            snapshot = self.symbols[self.symbol_names.index(name)]
            value = False
            if snapshot.has_previous:
                if operation == "changed": value = snapshot.current != snapshot.previous
                elif operation == "unchanged": value = snapshot.current == snapshot.previous
                elif operation == "increased": value = snapshot.current > snapshot.previous
                else: value = snapshot.current < snapshot.previous
            lines.append(DebugLine(path, value,
                f"{name}: previous={snapshot.previous!r}, current={snapshot.current!r}, op={operation}"))
            return value
        child = raw.get("condition")
        if isinstance(child, dict):
            self._explain(child, path + ".condition", lines)
        lines.append(DebugLine(path, None, f"stateful {operation}; see VM state slots"))
        return None
