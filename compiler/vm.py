"""Compiler, verifier, disassembler, and host evaluator for the AMUN VM."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
import math
import struct
from typing import Any, Sequence

from .diagnostics import DiagnosticReport


MAX_BYTECODE_BYTES = 256 * 1024
MAX_VM_STACK = 64
MAX_STATE_SLOTS = 256
MAX_INSTRUCTIONS = 2048
MAX_NESTING = 32


class Op(IntEnum):
    LOAD_CURRENT = 0x01
    LOAD_PREVIOUS = 0x02
    LOAD_INITIAL = 0x03
    CONST_I64 = 0x04
    CONST_F32 = 0x05
    CONST_BYTES = 0x06
    EQ = 0x10
    NE = 0x11
    LT = 0x12
    LE = 0x13
    GT = 0x14
    GE = 0x15
    BETWEEN = 0x16
    BIT_SET = 0x17
    BIT_CLEAR = 0x18
    MASKED_EQUALS = 0x19
    ADD = 0x1A
    SUBTRACT = 0x1B
    MULTIPLY = 0x1C
    DIVIDE = 0x1D
    BIT_AND = 0x1E
    BIT_OR = 0x1F
    CHANGED = 0x20
    UNCHANGED = 0x21
    INCREASED = 0x22
    DECREASED = 0x23
    INCREASED_BY = 0x24
    DECREASED_BY = 0x25
    ALL = 0x30
    ANY = 0x31
    NOT = 0x32
    RISING = 0x40
    FALLING = 0x41
    HIT_COUNT = 0x42
    CONSECUTIVE = 0x43
    LATCH = 0x44
    DURATION = 0x45
    COOLDOWN = 0x46
    SEQUENCE = 0x47
    RESET_IF = 0x48
    PAUSE_IF = 0x49
    SET_PROGRESS = 0x4A
    END = 0xFF


OP_ALIASES = {
    "==": "eq",
    "equals": "eq",
    "!=": "ne",
    "<": "lt",
    "<=": "le",
    ">": "gt",
    ">=": "ge",
    "bitset": "bit_set",
    "bitclear": "bit_clear",
    "masked_eq": "masked_equals",
    "increasedby": "increased_by",
    "decreasedby": "decreased_by",
    "hitcount": "hit_count",
    "one_shot": "rising",
    "one-shot": "rising",
    "progress": "set_progress",
    "+": "add",
    "-": "subtract",
    "*": "multiply",
    "/": "divide",
    "and_bits": "bit_and",
    "or_bits": "bit_or",
}


COMPARISON_OPS = {
    "eq": Op.EQ,
    "ne": Op.NE,
    "lt": Op.LT,
    "le": Op.LE,
    "gt": Op.GT,
    "ge": Op.GE,
}
HISTORY_OPS = {
    "changed": Op.CHANGED,
    "unchanged": Op.UNCHANGED,
    "increased": Op.INCREASED,
    "decreased": Op.DECREASED,
}
DELTA_OPS = {"increased_by": Op.INCREASED_BY, "decreased_by": Op.DECREASED_BY}
STATE_OPS = {"rising": Op.RISING, "falling": Op.FALLING, "latch": Op.LATCH}
ARITHMETIC_OPS = {
    "add": Op.ADD,
    "subtract": Op.SUBTRACT,
    "multiply": Op.MULTIPLY,
    "divide": Op.DIVIDE,
    "bit_and": Op.BIT_AND,
    "bit_or": Op.BIT_OR,
}


class BytecodeError(ValueError):
    pass


@dataclass(frozen=True)
class BytecodeInfo:
    maximum_stack: int
    state_slots: int
    instructions: int


@dataclass(frozen=True)
class CompiledCondition:
    code: bytes
    maximum_stack: int
    state_slots: int
    instructions: int
    progress_target: int = 0


class ConditionCompiler:
    def __init__(
        self,
        symbol_names: Sequence[str],
        report: DiagnosticReport,
        path: str,
    ) -> None:
        self.symbols = {name: index for index, name in enumerate(symbol_names)}
        self.report = report
        self.root_path = path
        self.code = bytearray()
        self.stack = 0
        self.maximum_stack = 0
        self.instructions = 0
        self.next_slot = 0
        self.progress_target = 0

    def compile(self, condition: Any) -> CompiledCondition | None:
        initial_errors = len(self.report.errors)
        self._condition(condition, self.root_path, 0)
        if self.stack != 1 and len(self.report.errors) == initial_errors:
            self.report.error(
                "E_VM_STACK",
                self.root_path,
                f"condition compiler ended with {self.stack} stack values instead of one",
            )
        self._emit(Op.END, b"", pop=0, push=0)
        if len(self.code) > MAX_BYTECODE_BYTES:
            self.report.error("E_BYTECODE_LIMIT", self.root_path, "compiled bytecode exceeds 256 KiB")
        if self.maximum_stack > MAX_VM_STACK:
            self.report.error(
                "E_VM_STACK_LIMIT",
                self.root_path,
                f"condition needs stack depth {self.maximum_stack}; limit is {MAX_VM_STACK}",
            )
        if self.instructions > MAX_INSTRUCTIONS:
            self.report.error(
                "E_VM_INSTRUCTION_LIMIT",
                self.root_path,
                f"condition needs {self.instructions} instructions; limit is {MAX_INSTRUCTIONS}",
            )
        if len(self.report.errors) != initial_errors:
            return None
        try:
            verified = verify_bytecode(bytes(self.code), len(self.symbols))
        except BytecodeError as error:
            self.report.error("E_BYTECODE_VERIFY", self.root_path, str(error))
            return None
        if (
            verified.maximum_stack != self.maximum_stack
            or verified.state_slots != self.next_slot
            or verified.instructions != self.instructions
        ):
            self.report.error(
                "E_COMPILER_INVARIANT",
                self.root_path,
                "independent bytecode verification disagreed with compiler accounting",
            )
            return None
        return CompiledCondition(
            bytes(self.code),
            verified.maximum_stack,
            verified.state_slots,
            verified.instructions,
            self.progress_target,
        )

    def compile_expression(self, expression: Any) -> CompiledCondition | None:
        initial_errors = len(self.report.errors)
        self._value(expression, self.root_path)
        if self.stack != 1 and len(self.report.errors) == initial_errors:
            self.report.error(
                "E_VM_STACK", self.root_path, "derived expression must produce exactly one value"
            )
        self._emit(Op.END, b"", pop=0, push=0)
        if len(self.code) > MAX_BYTECODE_BYTES:
            self.report.error("E_BYTECODE_LIMIT", self.root_path, "compiled bytecode exceeds 256 KiB")
        if self.maximum_stack > MAX_VM_STACK:
            self.report.error("E_VM_STACK_LIMIT", self.root_path, "derived expression exceeds VM stack limit")
        if self.instructions > MAX_INSTRUCTIONS:
            self.report.error(
                "E_VM_INSTRUCTION_LIMIT", self.root_path, "derived expression exceeds instruction limit"
            )
        if self.next_slot != 0:
            self.report.error("E_DERIVED_STATEFUL", self.root_path, "derived expressions cannot use state slots")
        if len(self.report.errors) != initial_errors:
            return None
        try:
            verified = verify_bytecode(bytes(self.code), len(self.symbols))
        except BytecodeError as error:
            self.report.error("E_BYTECODE_VERIFY", self.root_path, str(error))
            return None
        if verified.state_slots != 0:
            self.report.error("E_DERIVED_STATEFUL", self.root_path, "derived expressions must be stateless")
            return None
        return CompiledCondition(
            bytes(self.code), verified.maximum_stack, 0, verified.instructions, 0
        )

    def _emit(self, op: Op, operand: bytes, *, pop: int, push: int) -> None:
        if self.stack < pop:
            self.report.error("E_VM_STACK", self.root_path, f"internal stack underflow before {op.name}")
            self.stack = 0
        else:
            self.stack -= pop
        self.stack += push
        self.maximum_stack = max(self.maximum_stack, self.stack)
        self.code.append(int(op))
        self.code.extend(operand)
        self.instructions += 1

    def _slot(self, path: str) -> int:
        if self.next_slot > 0xFFFF:
            self.report.error("E_STATE_SLOT_LIMIT", path, "condition uses too many state slots")
            return 0
        slot = self.next_slot
        self.next_slot += 1
        return slot

    def _symbol(self, value: Any, path: str) -> int | None:
        if not isinstance(value, str) or value not in self.symbols:
            self.report.error("E_UNKNOWN_SYMBOL", path, f"unknown symbol {value!r}")
            return None
        return self.symbols[value]

    @staticmethod
    def _normalized_op(raw: Any) -> str:
        if not isinstance(raw, str):
            return ""
        original = raw.strip().lower()
        if original in {"+", "-", "*", "/"}:
            return OP_ALIASES[original]
        value = original.replace(" ", "_").replace("-", "_")
        return OP_ALIASES.get(value, value)

    def _constant(self, value: Any, path: str) -> None:
        if isinstance(value, bool):
            self._emit(Op.CONST_I64, struct.pack("<q", 1 if value else 0), pop=0, push=1)
            return
        if isinstance(value, int):
            if not -0x8000000000000000 <= value <= 0x7FFFFFFFFFFFFFFF:
                self.report.error("E_I64_RANGE", path, "integer constant exceeds signed 64-bit range")
                return
            self._emit(Op.CONST_I64, struct.pack("<q", value), pop=0, push=1)
            return
        if isinstance(value, float) and math.isfinite(value):
            try:
                encoded = struct.pack("<f", value)
                rounded = struct.unpack("<f", encoded)[0]
            except (OverflowError, struct.error):
                self.report.error("E_F32_RANGE", path, "floating constant cannot be represented as f32")
                return
            if not math.isfinite(rounded):
                self.report.error("E_F32_RANGE", path, "floating constant cannot be represented as finite f32")
                return
            self._emit(Op.CONST_F32, encoded, pop=0, push=1)
            return
        self.report.error("E_CONSTANT", path, "constant must be a finite number or Boolean")

    def _value(self, raw: Any, path: str, depth: int = 0) -> None:
        if depth > MAX_NESTING:
            self.report.error(
                "E_EXPRESSION_NESTING", path, f"value expression nesting exceeds {MAX_NESTING}"
            )
            return
        if isinstance(raw, (int, float, bool)):
            self._constant(raw, path)
            return
        if isinstance(raw, str):
            index = self._symbol(raw, path)
            if index is not None:
                self._emit(Op.LOAD_CURRENT, struct.pack("<H", index), pop=0, push=1)
            return
        if not isinstance(raw, dict):
            self.report.error("E_VALUE_EXPRESSION", path, "expected a symbol reference or constant")
            return
        if "bytes" in raw:
            encoded = self._byte_constant(raw.get("bytes"), path + ".bytes")
            if encoded is not None:
                self._emit(Op.CONST_BYTES, bytes((len(encoded),)) + encoded, pop=0, push=1)
            return
        if "string" in raw:
            value = raw.get("string")
            if not isinstance(value, str):
                self.report.error("E_BYTE_CONSTANT", path + ".string", "string constant must be text")
                return
            encoded = value.encode("utf-8")
            if not 1 <= len(encoded) <= 16:
                self.report.error(
                    "E_BYTE_CONSTANT", path + ".string", "UTF-8 string constant must occupy 1 through 16 bytes"
                )
                return
            self._emit(Op.CONST_BYTES, bytes((len(encoded),)) + encoded, pop=0, push=1)
            return
        value_op = self._normalized_op(raw.get("op"))
        if value_op in ARITHMETIC_OPS:
            self._value(raw.get("left"), path + ".left", depth + 1)
            self._value(raw.get("right"), path + ".right", depth + 1)
            self._emit(ARITHMETIC_OPS[value_op], b"", pop=2, push=1)
            return
        if "symbol" in raw:
            index = self._symbol(raw.get("symbol"), path + ".symbol")
            state = str(raw.get("state", "current")).lower()
            state_op = {
                "current": Op.LOAD_CURRENT,
                "previous": Op.LOAD_PREVIOUS,
                "initial": Op.LOAD_INITIAL,
            }.get(state)
            if state_op is None:
                self.report.error("E_SYMBOL_STATE", path + ".state", f"unsupported symbol state {state!r}")
            elif index is not None:
                self._emit(state_op, struct.pack("<H", index), pop=0, push=1)
            return
        if "const" in raw:
            self._constant(raw["const"], path + ".const")
            return
        if set(raw) == {"value"}:
            self._constant(raw["value"], path + ".value")
            return
        self.report.error(
            "E_VALUE_EXPRESSION",
            path,
            "bounded VM values support only symbol/current/previous/initial references or constants",
        )

    def _byte_constant(self, raw: Any, path: str) -> bytes | None:
        if isinstance(raw, str):
            tokens = raw.split()
            if not tokens or any(len(token) != 2 for token in tokens):
                self.report.error("E_BYTE_CONSTANT", path, "byte constant must be space-separated hex bytes")
                return None
            try:
                encoded = bytes(int(token, 16) for token in tokens)
            except ValueError:
                self.report.error("E_BYTE_CONSTANT", path, "byte constant contains invalid hexadecimal")
                return None
        elif isinstance(raw, list) and all(
            isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 255 for item in raw
        ):
            encoded = bytes(raw)
        else:
            self.report.error("E_BYTE_CONSTANT", path, "bytes must be a hex string or byte array")
            return None
        if not 1 <= len(encoded) <= 16:
            self.report.error("E_BYTE_CONSTANT", path, "byte constant must contain 1 through 16 bytes")
            return None
        return encoded

    def _condition(self, raw: Any, path: str, depth: int) -> None:
        if depth > MAX_NESTING:
            self.report.error("E_CONDITION_NESTING", path, f"condition nesting exceeds {MAX_NESTING}")
            return
        if isinstance(raw, bool):
            self._constant(raw, path)
            return
        if not isinstance(raw, dict):
            self.report.error("E_CONDITION", path, "condition must be an object")
            return

        if "all" in raw and "op" not in raw:
            op = "all"
            raw = {"op": "all", "conditions": raw["all"]}
        elif "any" in raw and "op" not in raw:
            op = "any"
            raw = {"op": "any", "conditions": raw["any"]}
        elif "not" in raw and "op" not in raw:
            op = "not"
            raw = {"op": "not", "condition": raw["not"]}
        else:
            op = self._normalized_op(raw.get("op"))
        if not op:
            self.report.error("E_CONDITION_OP", path, "condition requires an op")
            return

        if op in COMPARISON_OPS:
            left = raw.get("left", {"symbol": raw.get("symbol")})
            right = raw.get("right", raw.get("value"))
            self._value(left, path + ".left")
            self._value(right, path + ".right")
            self._emit(COMPARISON_OPS[op], b"", pop=2, push=1)
            return
        if op == "between":
            left = raw.get("left", {"symbol": raw.get("symbol")})
            lower = raw.get("lower", raw.get("min"))
            upper = raw.get("upper", raw.get("max"))
            self._value(left, path + ".left")
            self._value(lower, path + ".lower")
            self._value(upper, path + ".upper")
            self._emit(Op.BETWEEN, b"", pop=3, push=1)
            return
        if op in {"bit_set", "bit_clear"}:
            self._value(raw.get("left", {"symbol": raw.get("symbol")}), path + ".left")
            self._value(raw.get("mask", raw.get("value")), path + ".mask")
            self._emit(Op.BIT_SET if op == "bit_set" else Op.BIT_CLEAR, b"", pop=2, push=1)
            return
        if op == "masked_equals":
            self._value(raw.get("left", {"symbol": raw.get("symbol")}), path + ".left")
            self._value(raw.get("mask"), path + ".mask")
            self._value(raw.get("value"), path + ".value")
            self._emit(Op.MASKED_EQUALS, b"", pop=3, push=1)
            return
        if op in HISTORY_OPS:
            index = self._symbol(raw.get("symbol"), path + ".symbol")
            if index is not None:
                self._emit(HISTORY_OPS[op], struct.pack("<H", index), pop=0, push=1)
            return
        if op in DELTA_OPS:
            index = self._symbol(raw.get("symbol"), path + ".symbol")
            amount = raw.get("amount", raw.get("value"))
            if not isinstance(amount, int) or isinstance(amount, bool) or not 0 <= amount <= 0x7FFFFFFFFFFFFFFF:
                self.report.error(
                    "E_DELTA",
                    path + ".amount",
                    "increased_by/decreased_by amount must be a non-negative signed 64-bit integer",
                )
            elif index is not None:
                self._emit(DELTA_OPS[op], struct.pack("<Hq", index, amount), pop=0, push=1)
            return
        if op in {"all", "any"}:
            children = raw.get("conditions")
            if not isinstance(children, list) or not 1 <= len(children) <= 255:
                self.report.error("E_BOOLEAN_GROUP", path + ".conditions", "group needs 1 to 255 conditions")
                return
            for index, child in enumerate(children):
                self._condition(child, f"{path}.conditions[{index}]", depth + 1)
            self._emit(Op.ALL if op == "all" else Op.ANY, struct.pack("<B", len(children)), pop=len(children), push=1)
            return
        if op == "not":
            self._condition(raw.get("condition"), path + ".condition", depth + 1)
            self._emit(Op.NOT, b"", pop=1, push=1)
            return
        if op in STATE_OPS:
            self._condition(raw.get("condition"), path + ".condition", depth + 1)
            slot = self._slot(path)
            self._emit(STATE_OPS[op], struct.pack("<H", slot), pop=1, push=1)
            return
        if op in {"hit_count", "consecutive"}:
            self._condition(raw.get("condition"), path + ".condition", depth + 1)
            target = raw.get("count", raw.get("target"))
            if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= 0xFFFF:
                self.report.error("E_COUNTER_TARGET", path + ".count", "counter target must be 1 through 65535")
                target = 1
            slot = self._slot(path)
            self._emit(
                Op.HIT_COUNT if op == "hit_count" else Op.CONSECUTIVE,
                struct.pack("<HH", slot, target),
                pop=1,
                push=1,
            )
            return
        if op in {"duration", "cooldown"}:
            self._condition(raw.get("condition"), path + ".condition", depth + 1)
            target = raw.get("milliseconds", raw.get("durationMs", raw.get("target")))
            if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= 0xFFFFFFFF:
                self.report.error("E_TIMER_TARGET", path, "timer duration must be 1 through 4294967295 ms")
                target = 1
            slot = self._slot(path)
            self._emit(
                Op.DURATION if op == "duration" else Op.COOLDOWN,
                struct.pack("<HI", slot, target),
                pop=1,
                push=1,
            )
            return
        if op == "sequence":
            children = raw.get("conditions")
            if not isinstance(children, list) or not 1 <= len(children) <= 255:
                self.report.error("E_SEQUENCE", path + ".conditions", "sequence needs 1 to 255 conditions")
                return
            for index, child in enumerate(children):
                self._condition(child, f"{path}.conditions[{index}]", depth + 1)
            slot = self._slot(path)
            self._emit(Op.SEQUENCE, struct.pack("<HB", slot, len(children)), pop=len(children), push=1)
            return
        if op in {"reset_if", "pause_if"}:
            self._condition(raw.get("condition"), path + ".condition", depth + 1)
            gate_key = "reset" if op == "reset_if" else "pause"
            self._condition(raw.get(gate_key), f"{path}.{gate_key}", depth + 1)
            self._emit(Op.RESET_IF if op == "reset_if" else Op.PAUSE_IF, b"", pop=2, push=1)
            return
        if op == "set_progress":
            if "symbol" in raw and "value" not in raw:
                value_expression: Any = {"symbol": raw.get("symbol"), "state": raw.get("state", "current")}
            else:
                value_expression = raw.get("value")
            self._value(value_expression, path + ".value")
            target = raw.get("target")
            if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= 0xFFFFFFFF:
                self.report.error("E_PROGRESS_TARGET", path + ".target", "progress target must be 1 through 4294967295")
                target = 1
            self.progress_target = target
            self._emit(Op.SET_PROGRESS, struct.pack("<I", target), pop=1, push=1)
            return
        self.report.error("E_CONDITION_OP", path + ".op", f"unsupported condition operation {op!r}")


def compile_condition(
    condition: Any,
    symbol_names: Sequence[str],
    report: DiagnosticReport,
    path: str,
) -> CompiledCondition | None:
    return ConditionCompiler(symbol_names, report, path).compile(condition)


def compile_expression(
    expression: Any,
    symbol_names: Sequence[str],
    report: DiagnosticReport,
    path: str,
) -> CompiledCondition | None:
    """Compile a bounded, stateless derived-symbol expression."""

    return ConditionCompiler(symbol_names, report, path).compile_expression(expression)


def _take(code: bytes, cursor: int, fmt: str, description: str) -> tuple[tuple[Any, ...], int]:
    size = struct.calcsize(fmt)
    if cursor + size > len(code):
        raise BytecodeError(f"truncated {description} at byte {cursor}")
    return struct.unpack_from(fmt, code, cursor), cursor + size


def verify_bytecode(code: bytes, symbol_count: int) -> BytecodeInfo:
    if not code or len(code) > MAX_BYTECODE_BYTES:
        raise BytecodeError("empty or oversized bytecode")
    cursor = 0
    stack = 0
    maximum_stack = 0
    slot_maximum = 0
    instructions = 0
    ended = False
    while cursor < len(code):
        instruction_at = cursor
        instructions += 1
        if instructions > MAX_INSTRUCTIONS:
            raise BytecodeError("instruction limit exceeded")
        raw = code[cursor]
        cursor += 1
        try:
            op = Op(raw)
        except ValueError as error:
            raise BytecodeError(f"unknown opcode {raw} at byte {instruction_at}") from error

        required, produced = 0, 0
        slot: int | None = None
        if op in {Op.LOAD_CURRENT, Op.LOAD_PREVIOUS, Op.LOAD_INITIAL}:
            (symbol,), cursor = _take(code, cursor, "<H", "symbol operand")
            if symbol >= symbol_count:
                raise BytecodeError(f"symbol index out of range at byte {cursor}")
            produced = 1
        elif op == Op.CONST_I64:
            _, cursor = _take(code, cursor, "<q", "integer constant")
            produced = 1
        elif op == Op.CONST_F32:
            (value,), cursor = _take(code, cursor, "<f", "float constant")
            if not math.isfinite(value):
                raise BytecodeError("invalid float constant")
            produced = 1
        elif op == Op.CONST_BYTES:
            (count,), cursor = _take(code, cursor, "<B", "byte-sequence length")
            if not 1 <= count <= 16 or cursor + count > len(code):
                raise BytecodeError("invalid byte-sequence constant")
            cursor += count
            produced = 1
        elif op in {
            Op.EQ, Op.NE, Op.LT, Op.LE, Op.GT, Op.GE, Op.BIT_SET, Op.BIT_CLEAR,
            Op.ADD, Op.SUBTRACT, Op.MULTIPLY, Op.DIVIDE, Op.BIT_AND, Op.BIT_OR,
        }:
            required, produced = 2, 1
        elif op in {Op.BETWEEN, Op.MASKED_EQUALS}:
            required, produced = 3, 1
        elif op in {Op.CHANGED, Op.UNCHANGED, Op.INCREASED, Op.DECREASED}:
            (symbol,), cursor = _take(code, cursor, "<H", "history operand")
            if symbol >= symbol_count:
                raise BytecodeError(f"symbol index out of range at byte {cursor}")
            produced = 1
        elif op in {Op.INCREASED_BY, Op.DECREASED_BY}:
            (symbol, _amount), cursor = _take(code, cursor, "<Hq", "delta operand")
            if symbol >= symbol_count:
                raise BytecodeError(f"symbol index out of range at byte {cursor}")
            produced = 1
        elif op in {Op.ALL, Op.ANY}:
            (count,), cursor = _take(code, cursor, "<B", "Boolean group count")
            if count == 0:
                raise BytecodeError("invalid Boolean group")
            required, produced = count, 1
        elif op == Op.NOT:
            required, produced = 1, 1
        elif op in {Op.RISING, Op.FALLING, Op.LATCH}:
            (slot,), cursor = _take(code, cursor, "<H", "state operand")
            required, produced = 1, 1
        elif op in {Op.HIT_COUNT, Op.CONSECUTIVE}:
            (slot, target), cursor = _take(code, cursor, "<HH", "counter operand")
            if target == 0:
                raise BytecodeError("invalid counter operand")
            required, produced = 1, 1
        elif op in {Op.DURATION, Op.COOLDOWN}:
            (slot, target), cursor = _take(code, cursor, "<HI", "timer operand")
            if target == 0:
                raise BytecodeError("invalid timer operand")
            required, produced = 1, 1
        elif op == Op.SEQUENCE:
            (slot, count), cursor = _take(code, cursor, "<HB", "sequence operand")
            if count == 0:
                raise BytecodeError("invalid sequence operand")
            required, produced = count, 1
        elif op in {Op.RESET_IF, Op.PAUSE_IF}:
            required, produced = 2, 1
        elif op == Op.SET_PROGRESS:
            (target,), cursor = _take(code, cursor, "<I", "progress target")
            if target == 0:
                raise BytecodeError("invalid progress target")
            required, produced = 1, 1
        elif op == Op.END:
            if cursor != len(code) or stack != 1:
                raise BytecodeError("END must terminate a program with exactly one result")
            ended = True
        if stack < required:
            raise BytecodeError(f"stack underflow at byte {instruction_at}")
        stack = stack - required + produced
        maximum_stack = max(maximum_stack, stack)
        if maximum_stack > MAX_VM_STACK:
            raise BytecodeError("VM stack limit exceeded")
        if slot is not None:
            slot_maximum = max(slot_maximum, slot + 1)
            if slot_maximum > MAX_STATE_SLOTS:
                raise BytecodeError("state slot limit exceeded")
        if ended:
            break
    if not ended:
        raise BytecodeError("program has no END")
    return BytecodeInfo(maximum_stack, slot_maximum, instructions)


def disassemble(code: bytes, symbol_names: Sequence[str] = ()) -> list[str]:
    # Verification first prevents the formatter from needing recovery rules.
    verify_bytecode(code, max(len(symbol_names), 65536) if not symbol_names else len(symbol_names))
    cursor = 0
    lines: list[str] = []
    while cursor < len(code):
        at = cursor
        op = Op(code[cursor])
        cursor += 1
        operand = ""
        if op in {Op.LOAD_CURRENT, Op.LOAD_PREVIOUS, Op.LOAD_INITIAL, Op.CHANGED, Op.UNCHANGED, Op.INCREASED, Op.DECREASED}:
            (index,), cursor = _take(code, cursor, "<H", "symbol")
            name = symbol_names[index] if index < len(symbol_names) else str(index)
            operand = name
        elif op == Op.CONST_I64:
            (value,), cursor = _take(code, cursor, "<q", "constant")
            operand = str(value)
        elif op == Op.CONST_F32:
            (value,), cursor = _take(code, cursor, "<f", "constant")
            operand = format(value, ".9g")
        elif op == Op.CONST_BYTES:
            (count,), cursor = _take(code, cursor, "<B", "byte count")
            value = code[cursor : cursor + count]
            cursor += count
            operand = value.hex(" ").upper()
        elif op in {Op.INCREASED_BY, Op.DECREASED_BY}:
            (index, amount), cursor = _take(code, cursor, "<Hq", "delta")
            name = symbol_names[index] if index < len(symbol_names) else str(index)
            operand = f"{name}, {amount}"
        elif op in {Op.ALL, Op.ANY}:
            (count,), cursor = _take(code, cursor, "<B", "count")
            operand = str(count)
        elif op in {Op.RISING, Op.FALLING, Op.LATCH}:
            (slot,), cursor = _take(code, cursor, "<H", "slot")
            operand = f"slot={slot}"
        elif op in {Op.HIT_COUNT, Op.CONSECUTIVE}:
            (slot, target), cursor = _take(code, cursor, "<HH", "counter")
            operand = f"slot={slot}, target={target}"
        elif op in {Op.DURATION, Op.COOLDOWN}:
            (slot, target), cursor = _take(code, cursor, "<HI", "timer")
            operand = f"slot={slot}, milliseconds={target}"
        elif op == Op.SEQUENCE:
            (slot, count), cursor = _take(code, cursor, "<HB", "sequence")
            operand = f"slot={slot}, count={count}"
        elif op == Op.SET_PROGRESS:
            (target,), cursor = _take(code, cursor, "<I", "progress")
            operand = f"target={target}"
        lines.append(f"{at:04X}  {op.name}{(' ' + operand) if operand else ''}")
    return lines


@dataclass
class SymbolState:
    current: int | float | bytes
    previous: int | float | bytes = 0
    initial: int | float | bytes = 0
    has_previous: bool = False
    has_initial: bool = False
    valid: bool = True


@dataclass
class SlotState:
    count: int = 0
    stage: int = 0
    started_at: int = 0
    last_at: int = 0
    previous: bool = False
    latched: bool = False
    active: bool = False


@dataclass
class VmState:
    slots: list[SlotState]
    paused: bool = False

    @classmethod
    def with_slots(cls, count: int) -> "VmState":
        return cls([SlotState() for _ in range(count)])

    def reset(self) -> None:
        self.slots = [SlotState() for _ in self.slots]
        self.paused = False


@dataclass(frozen=True)
class EvalResult:
    condition: bool
    progress: int
    instructions: int
    value: int | float | bytes


def _truthy(value: int | float | bytes) -> bool:
    return any(value) if isinstance(value, bytes) else value != 0


def _f32(value: float) -> float:
    try:
        rounded = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as error:
        raise BytecodeError("non-finite arithmetic result") from error
    if not math.isfinite(rounded):
        raise BytecodeError("non-finite arithmetic result")
    return rounded


def _saturate(value: int) -> int:
    return min(max(value, -0x8000000000000000), 0x7FFFFFFFFFFFFFFF)


def _as_integer(value: int | float | bytes) -> int:
    if isinstance(value, bytes):
        return 0
    return int(value)


def _as_double(value: int | float | bytes) -> float:
    return 0.0 if isinstance(value, bytes) else float(value)


def evaluate_bytecode(
    code: bytes,
    symbols: Sequence[SymbolState],
    monotonic_ms: int,
    state: VmState,
    instruction_budget: int,
    stack_limit: int,
) -> EvalResult:
    verified = verify_bytecode(code, len(symbols))
    if verified.maximum_stack > stack_limit or verified.state_slots > len(state.slots):
        raise BytecodeError("declared VM limits are too small")
    cursor = 0
    stack: list[int | float | bytes] = []
    progress = 0
    instructions = 0
    initial_slots = [replace(slot) for slot in state.slots]
    initial_paused = state.paused

    def pop() -> int | float | bytes:
        if not stack:
            raise BytecodeError("VM stack underflow")
        return stack.pop()

    def push(value: int | float | bytes) -> None:
        if len(stack) >= stack_limit:
            raise BytecodeError("VM stack overflow")
        stack.append(value)

    while cursor < len(code):
        instructions += 1
        if instructions > instruction_budget:
            raise BytecodeError("runtime instruction budget exceeded")
        op = Op(code[cursor])
        cursor += 1
        if op in {Op.LOAD_CURRENT, Op.LOAD_PREVIOUS, Op.LOAD_INITIAL}:
            (index,), cursor = _take(code, cursor, "<H", "symbol")
            snapshot = symbols[index]
            if not snapshot.valid:
                raise BytecodeError("unavailable symbol")
            value = snapshot.current
            if op == Op.LOAD_PREVIOUS and snapshot.has_previous:
                value = snapshot.previous
            elif op == Op.LOAD_INITIAL and snapshot.has_initial:
                value = snapshot.initial
            push(value)
        elif op == Op.CONST_I64:
            (value,), cursor = _take(code, cursor, "<q", "constant")
            push(value)
        elif op == Op.CONST_F32:
            (value,), cursor = _take(code, cursor, "<f", "constant")
            push(value)
        elif op == Op.CONST_BYTES:
            (count,), cursor = _take(code, cursor, "<B", "byte count")
            push(code[cursor : cursor + count])
            cursor += count
        elif op in {
            Op.EQ, Op.NE, Op.LT, Op.LE, Op.GT, Op.GE, Op.BIT_SET, Op.BIT_CLEAR,
            Op.ADD, Op.SUBTRACT, Op.MULTIPLY, Op.DIVIDE, Op.BIT_AND, Op.BIT_OR,
        }:
            right, left = pop(), pop()
            if (isinstance(left, bytes) or isinstance(right, bytes)) and op not in {Op.EQ, Op.NE}:
                raise BytecodeError("invalid operation on byte sequence")
            if op == Op.EQ:
                value = left == right
            elif op == Op.NE:
                value = left != right
            elif op == Op.LT:
                value = left < right
            elif op == Op.LE:
                value = left <= right
            elif op == Op.GT:
                value = left > right
            elif op == Op.GE:
                value = left >= right
            elif op == Op.BIT_SET:
                value = (_as_integer(left) & _as_integer(right)) == _as_integer(right)
            elif op == Op.BIT_CLEAR:
                value = (_as_integer(left) & _as_integer(right)) == 0
            elif op == Op.ADD:
                push(_f32(float(left) + float(right)) if isinstance(left, float) or isinstance(right, float) else _saturate(left + right))
                continue
            elif op == Op.SUBTRACT:
                push(_f32(float(left) - float(right)) if isinstance(left, float) or isinstance(right, float) else _saturate(left - right))
                continue
            elif op == Op.MULTIPLY:
                push(_f32(float(left) * float(right)) if isinstance(left, float) or isinstance(right, float) else _saturate(left * right))
                continue
            elif op == Op.DIVIDE:
                if float(right) == 0.0:
                    raise BytecodeError("division by zero")
                if isinstance(left, float) or isinstance(right, float):
                    push(_f32(float(left) / float(right)))
                elif left == -0x8000000000000000 and right == -1:
                    push(0x7FFFFFFFFFFFFFFF)
                else:
                    quotient = abs(left) // abs(right)
                    push(-quotient if (left < 0) != (right < 0) else quotient)
                continue
            elif op == Op.BIT_AND:
                push(_as_integer(left) & _as_integer(right))
                continue
            else:
                push(_as_integer(left) | _as_integer(right))
                continue
            push(1 if value else 0)
        elif op in {Op.BETWEEN, Op.MASKED_EQUALS}:
            third, right, left = pop(), pop(), pop()
            value = (
                _as_double(right) <= _as_double(left) <= _as_double(third)
                if op == Op.BETWEEN
                else (_as_integer(left) & _as_integer(right)) == _as_integer(third)
            )
            push(1 if value else 0)
        elif op in {Op.CHANGED, Op.UNCHANGED, Op.INCREASED, Op.DECREASED}:
            (index,), cursor = _take(code, cursor, "<H", "history")
            snapshot = symbols[index]
            if not snapshot.valid:
                raise BytecodeError("unavailable history symbol")
            value = False
            if snapshot.has_previous:
                if op == Op.CHANGED:
                    value = snapshot.current != snapshot.previous
                elif op == Op.UNCHANGED:
                    value = snapshot.current == snapshot.previous
                elif op == Op.INCREASED:
                    value = _as_double(snapshot.current) > _as_double(snapshot.previous)
                else:
                    value = _as_double(snapshot.current) < _as_double(snapshot.previous)
            push(1 if value else 0)
        elif op in {Op.INCREASED_BY, Op.DECREASED_BY}:
            (index, amount), cursor = _take(code, cursor, "<Hq", "delta")
            snapshot = symbols[index]
            if not snapshot.valid:
                raise BytecodeError("unavailable delta symbol")
            delta = _as_double(snapshot.current) - _as_double(snapshot.previous)
            value = snapshot.has_previous and delta == (
                amount if op == Op.INCREASED_BY else -amount
            )
            push(1 if value else 0)
        elif op in {Op.ALL, Op.ANY}:
            (count,), cursor = _take(code, cursor, "<B", "group")
            values = [_truthy(pop()) for _ in range(count)]
            push(1 if (all(values) if op == Op.ALL else any(values)) else 0)
        elif op == Op.NOT:
            push(0 if _truthy(pop()) else 1)
        elif op in {Op.RISING, Op.FALLING, Op.LATCH}:
            (slot_index,), cursor = _take(code, cursor, "<H", "state")
            slot = state.slots[slot_index]
            current = _truthy(pop())
            if op in {Op.RISING, Op.FALLING}:
                if not slot.active:
                    slot.active = True
                    value = False
                elif op == Op.RISING:
                    value = current and not slot.previous
                else:
                    value = not current and slot.previous
            else:
                if current:
                    slot.latched = True
                value = slot.latched
            slot.previous = current
            push(1 if value else 0)
        elif op in {Op.HIT_COUNT, Op.CONSECUTIVE}:
            (slot_index, target), cursor = _take(code, cursor, "<HH", "counter")
            slot = state.slots[slot_index]
            current = _truthy(pop())
            if op == Op.HIT_COUNT:
                if not slot.active:
                    slot.active = True
                elif current and not slot.previous and slot.count < target:
                    slot.count += 1
                slot.previous = current
            else:
                slot.count = min(slot.count + 1, target) if current else 0
            push(1 if slot.count >= target else 0)
        elif op == Op.DURATION:
            (slot_index, target), cursor = _take(code, cursor, "<HI", "duration")
            slot = state.slots[slot_index]
            current = _truthy(pop())
            if current and not slot.active:
                slot.active = True
                slot.started_at = monotonic_ms
            elif not current:
                slot.active = False
                slot.started_at = 0
            value = current and slot.active and monotonic_ms >= slot.started_at and monotonic_ms - slot.started_at >= target
            push(1 if value else 0)
        elif op == Op.COOLDOWN:
            (slot_index, target), cursor = _take(code, cursor, "<HI", "cooldown")
            slot = state.slots[slot_index]
            current = _truthy(pop())
            edge = current and not slot.previous
            elapsed = not slot.latched or (monotonic_ms >= slot.last_at and monotonic_ms - slot.last_at >= target)
            value = edge and elapsed
            if value:
                slot.latched = True
                slot.last_at = monotonic_ms
            slot.previous = current
            push(1 if value else 0)
        elif op == Op.SEQUENCE:
            (slot_index, count), cursor = _take(code, cursor, "<HB", "sequence")
            slot = state.slots[slot_index]
            conditions = [False] * count
            for index in range(count - 1, -1, -1):
                conditions[index] = _truthy(pop())
            if not slot.active and slot.stage < count:
                slot.active = True
                slot.previous = conditions[slot.stage]
            elif slot.stage < count:
                current = conditions[slot.stage]
                if current and not slot.previous:
                    slot.stage += 1
                    slot.previous = conditions[slot.stage] if slot.stage < count else False
                else:
                    slot.previous = current
            push(1 if slot.stage >= count else 0)
        elif op == Op.RESET_IF:
            gate, value = _truthy(pop()), pop()
            if gate:
                state.reset()
                value = 0
            push(value)
        elif op == Op.PAUSE_IF:
            gate, value = _truthy(pop()), pop()
            state.paused = gate
            if state.paused:
                state.slots = [replace(slot) for slot in initial_slots]
            elif initial_paused:
                state.paused = False
            push(1 if not state.paused and _truthy(value) else 0)
        elif op == Op.SET_PROGRESS:
            (target,), cursor = _take(code, cursor, "<I", "progress")
            raw_value = pop()
            raw = max(0.0, _as_double(raw_value))
            progress = int(min(raw, target))
            push(1 if progress >= target else 0)
        elif op == Op.END:
            if cursor != len(code) or len(stack) != 1:
                raise BytecodeError("invalid END state")
            return EvalResult(_truthy(stack[-1]), progress, instructions, stack[-1])
    raise BytecodeError("program ended without END")
