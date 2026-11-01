from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import runpy
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from cli.main import main as cli_main
from compiler.diagnostics import CompilationFailed, DiagnosticReport
from compiler.dump import diff_dumps, search_dump
from compiler.importer import import_ra_document
from compiler.pack import (
    ACHIEVEMENT,
    ASSET,
    BUILD,
    HEADER,
    MAX_PACK_BYTES,
    SECTION,
    SYMBOL,
    PackError,
    compile_profile,
    inspect_pack,
)
from compiler.profile import LoadedProfile, load_profile
from compiler.simulator import run_profile_tests
from compiler.trace import FRAME_HEADER, READ_HEADER, TRACE_HEADER, TraceError, inspect_trace
from compiler.vm import (
    BytecodeError,
    Op,
    SymbolState,
    VmState,
    compile_condition,
    compile_expression,
    evaluate_bytecode,
    verify_bytecode,
)


REPOSITORY = Path(__file__).resolve().parents[2]
SYNTHETIC = REPOSITORY / "profiles" / "synthetic" / "profile.json"


def synthetic_document() -> dict:
    return json.loads(SYNTHETIC.read_text(encoding="utf-8"))


def no_asset_document() -> dict:
    document = synthetic_document()
    document["assets"] = {}
    for achievement in document["achievements"]:
        achievement.pop("icon", None)
    return document


def unpack_pack_sections(data: bytes) -> tuple[int, bytes, list[list[object]]]:
    fields = HEADER.unpack_from(data)
    flags = fields[5]
    profile_hash = fields[8]
    sections: list[list[object]] = []
    for index in range(fields[6]):
        section_type, offset, size, count = SECTION.unpack_from(
            data, HEADER.size + index * SECTION.size
        )
        sections.append([section_type, bytearray(data[offset : offset + size]), count])
    return flags, profile_hash, sections


def rebuild_pack(flags: int, profile_hash: bytes, sections: list[list[object]]) -> bytes:
    header_size = HEADER.size + len(sections) * SECTION.size
    cursor = header_size
    directory = bytearray()
    payload = bytearray()
    for section_type, raw_data, count in sections:
        section_data = bytes(raw_data)
        directory.extend(SECTION.pack(int(section_type), cursor, len(section_data), int(count)))
        payload.extend(section_data)
        cursor += len(section_data)
    return bytes(
        HEADER.pack(
            b"AMUN",
            1,
            0,
            cursor,
            zlib.crc32(payload) & 0xFFFFFFFF,
            flags,
            len(sections),
            header_size,
            profile_hash,
        )
        + directory
        + payload
    )


def section_entry(sections: list[list[object]], section_type: int) -> list[object]:
    return next(section for section in sections if section[0] == section_type)


class CompilerTests(unittest.TestCase):
    def _condition_program(self, condition: dict, symbols: list[str]):
        report = DiagnosticReport()
        program = compile_condition(condition, symbols, report, "$.condition")
        self.assertTrue(report.ok, report.format())
        self.assertIsNotNone(program)
        return program

    def test_synthetic_profile_compiles_and_self_inspects(self) -> None:
        compiled = compile_profile(load_profile(SYNTHETIC))
        inspected = inspect_pack(compiled.data)
        self.assertEqual("AMUN", inspected["format"])
        self.assertEqual("1.0", inspected["version"])
        self.assertEqual("000400000FF40A00", inspected["manifest"]["titleId"])
        self.assertEqual(11, len(inspected["symbols"]))
        self.assertEqual(14, len(inspected["achievements"]))
        self.assertEqual("icon.boss", inspected["assets"][0]["name"])
        self.assertEqual(8, inspected["assets"][0]["decodedSize"])

    def test_compilation_is_byte_for_byte_deterministic(self) -> None:
        document = synthetic_document()
        first = compile_profile(document, project_root=SYNTHETIC.parent)
        second = compile_profile(copy.deepcopy(document), project_root=SYNTHETIC.parent)
        reordered = {key: document[key] for key in reversed(document)}
        third = compile_profile(reordered, project_root=SYNTHETIC.parent)
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.data, third.data)
        self.assertEqual(first.profile_hash, third.profile_hash)

    def test_exact_header_crc_and_record_sizes(self) -> None:
        compiled = compile_profile(load_profile(SYNTHETIC))
        fields = HEADER.unpack_from(compiled.data)
        self.assertEqual(b"AMUN", fields[0])
        self.assertEqual((1, 0), fields[1:3])
        self.assertEqual(len(compiled.data), fields[3])
        self.assertEqual(9, fields[6])
        self.assertEqual(40 + 9 * 16, fields[7])
        self.assertEqual(fields[4], zlib.crc32(compiled.data[fields[7] :]) & 0xFFFFFFFF)
        self.assertEqual(32, SYMBOL.size)
        self.assertEqual(56, ACHIEVEMENT.size)
        self.assertEqual(24, ASSET.size)

    def test_no_asset_profile_uses_only_seven_sections(self) -> None:
        compiled = compile_profile(no_asset_document(), project_root=SYNTHETIC.parent)
        inspected = inspect_pack(compiled.data)
        self.assertEqual(7, len(inspected["sections"]))
        self.assertEqual([], inspected["assets"])
        self.assertEqual(set(range(1, 8)), {item["type"] for item in inspected["sections"]})

    def test_derived_symbols_are_dependency_ordered_and_stateless(self) -> None:
        compiled = compile_profile(load_profile(SYNTHETIC))
        inspected = inspect_pack(compiled.data)
        names = [item["name"] for item in inspected["symbols"]]
        self.assertLess(names.index("player.hp"), names.index("player.hp_percent"))
        self.assertLess(names.index("player.max_hp"), names.index("player.hp_percent"))
        derived = next(item for item in inspected["symbols"] if item["name"] == "player.hp_percent")
        bytecode = derived["derivedBytecode"]
        self.assertEqual(0, bytecode["stateSlots"])
        self.assertIn("MULTIPLY", "\n".join(bytecode["disassembly"]))
        self.assertIn("DIVIDE", "\n".join(bytecode["disassembly"]))

    def test_bare_derived_reference_is_dependency_ordered(self) -> None:
        document = no_asset_document()
        document["symbols"]["z.source"] = {
            "type": "u32",
            "resolver": {"kind": "absolute", "address": "0x08002000"},
        }
        document["symbols"]["a.derived"] = {
            "type": "u32",
            "resolver": {"kind": "derived", "expression": "z.source"},
        }
        names = list(
            compile_profile(document, project_root=SYNTHETIC.parent).symbol_names
        )
        self.assertLess(names.index("z.source"), names.index("a.derived"))

    def test_derived_cycle_is_rejected_with_specific_diagnostic(self) -> None:
        document = no_asset_document()
        document["symbols"]["cycle.a"] = {
            "type": "u32",
            "resolver": {"kind": "derived", "expression": {"symbol": "cycle.b"}},
        }
        document["symbols"]["cycle.b"] = {
            "type": "u32",
            "resolver": {"kind": "derived", "expression": {"symbol": "cycle.a"}},
        }
        with self.assertRaises(CompilationFailed) as caught:
            compile_profile(document, project_root=SYNTHETIC.parent)
        self.assertIn("E_DERIVED_CYCLE", {item.code for item in caught.exception.report.errors})

    def test_every_build_requires_a_known_exact_fingerprint_scheme(self) -> None:
        document = no_asset_document()
        document["game"]["builds"][0]["codeFingerprint"] = "not-a-fingerprint"
        with self.assertRaises(CompilationFailed) as caught:
            compile_profile(document, project_root=SYNTHETIC.parent)
        self.assertIn("E_EXACT_FINGERPRINT", {item.code for item in caught.exception.report.errors})

    def test_immediate_unconditional_unlocks_are_rejected(self) -> None:
        for trigger in (
            True,
            {"any": [False, True]},
            {"op": "eq", "left": {"const": 1}, "right": 1},
        ):
            document = no_asset_document()
            document["achievements"][0]["trigger"] = trigger
            with self.assertRaises(CompilationFailed) as caught:
                compile_profile(document, project_root=SYNTHETIC.parent)
            self.assertIn(
                "E_UNCONDITIONAL_UNLOCK",
                {item.code for item in caught.exception.report.errors},
            )

    def test_live_hardware_fingerprint_builds_and_round_trips_exactly(self) -> None:
        document = no_asset_document()
        hardware_fingerprint = "live-text-crc32-v1:00123456:89ABCDEF"
        document["game"]["builds"][0]["codeFingerprint"] = hardware_fingerprint
        inspected = inspect_pack(compile_profile(document, project_root=SYNTHETIC.parent).data)
        self.assertEqual(hardware_fingerprint, inspected["builds"][0]["codeFingerprint"])

    def test_fixed_bytes_value_size_and_const_bytes(self) -> None:
        inspected = inspect_pack(compile_profile(load_profile(SYNTHETIC)).data)
        state_name = next(item for item in inspected["symbols"] if item["name"] == "state.name")
        ready = next(item for item in inspected["achievements"] if item["id"] == "ready_state")
        self.assertEqual(8, state_name["valueSize"])
        self.assertIn("CONST_BYTES", "\n".join(ready["disassembly"]))

    def test_malformed_crc_directory_and_bytecode_are_rejected(self) -> None:
        original = bytearray(compile_profile(no_asset_document(), project_root=SYNTHETIC.parent).data)
        bad_crc = bytearray(original)
        bad_crc[-1] ^= 1
        with self.assertRaisesRegex(PackError, "CRC"):
            inspect_pack(bad_crc)

        bad_directory = bytearray(original)
        struct.pack_into("<I", bad_directory, HEADER.size + 4, len(bad_directory) + 100)
        with self.assertRaisesRegex(PackError, "outside"):
            inspect_pack(bad_directory)

        bad_code = bytearray(original)
        fields = HEADER.unpack_from(bad_code)
        header_size = fields[7]
        bytecode_offset = None
        for index in range(fields[6]):
            section_type, offset, size, count = SECTION.unpack_from(bad_code, HEADER.size + index * SECTION.size)
            if section_type == 6:
                bytecode_offset = offset
                break
        self.assertIsNotNone(bytecode_offset)
        bad_code[bytecode_offset] = 0xFE
        struct.pack_into("<I", bad_code, 12, zlib.crc32(bad_code[header_size:]) & 0xFFFFFFFF)
        with self.assertRaisesRegex(PackError, "bytecode"):
            inspect_pack(bad_code)

    def test_inspector_enforces_fixed_object_string_and_prerequisite_limits(self) -> None:
        original = compile_profile(load_profile(SYNTHETIC)).data

        flags, profile_hash, sections = unpack_pack_sections(original)
        builds = section_entry(sections, 2)
        builds[1] = bytearray(bytes(builds[1])[: BUILD.size] * 65)
        builds[2] = 65
        with self.assertRaisesRegex(PackError, "build count"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

        flags, profile_hash, sections = unpack_pack_sections(original)
        strings = section_entry(sections, 7)
        missing_entries = 8193 - int(strings[2])
        strings[1].extend(b"\0" * missing_entries)
        strings[2] = 8193
        with self.assertRaisesRegex(PackError, "string table count"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

        flags, profile_hash, sections = unpack_pack_sections(original)
        strings = section_entry(sections, 7)
        long_string_offset = len(strings[1])
        strings[1].extend(b"x" * 1024 + b"\0")
        strings[2] = int(strings[2]) + 1
        achievements = section_entry(sections, 4)
        first = list(ACHIEVEMENT.unpack_from(achievements[1]))
        first[:8] = [long_string_offset] * 8
        record = ACHIEVEMENT.pack(*first)
        achievements[1] = bytearray(record * 500)
        achievements[2] = 500
        with self.assertRaisesRegex(PackError, "referenced string bytes"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

        flags, profile_hash, sections = unpack_pack_sections(original)
        strings = section_entry(sections, 7)
        prerequisites_offset = len(strings[1])
        strings[1].extend((",".join(["required"] * 33)).encode("utf-8") + b"\0")
        strings[2] = int(strings[2]) + 1
        achievements = section_entry(sections, 4)
        first = list(ACHIEVEMENT.unpack_from(achievements[1]))
        first[7] = prerequisites_offset
        achievements[1][: ACHIEVEMENT.size] = ACHIEVEMENT.pack(*first)
        with self.assertRaisesRegex(PackError, "prerequisites"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

        with self.assertRaisesRegex(PackError, "2 MiB"):
            inspect_pack(b"x" * (MAX_PACK_BYTES + 1))

    def test_inspector_charges_aliased_bytecode_assets_and_vm_state(self) -> None:
        original = compile_profile(load_profile(SYNTHETIC)).data

        flags, profile_hash, sections = unpack_pack_sections(original)
        maximum_program = (
            bytes((Op.CONST_I64,))
            + struct.pack("<q", 1)
            + bytes((Op.NOT,)) * 2046
            + bytes((Op.END,))
        )
        bytecode = section_entry(sections, 6)
        bytecode[1] = bytearray(maximum_program)
        bytecode[2] = 1
        symbols = section_entry(sections, 3)
        rewritten_symbols = bytearray()
        for at in range(0, len(symbols[1]), SYMBOL.size):
            fields = list(SYMBOL.unpack_from(symbols[1], at))
            if fields[3] == 4:
                fields[3] = 0
                fields[11] = 0
                fields[12] = 0
            rewritten_symbols.extend(SYMBOL.pack(*fields))
        symbols[1] = rewritten_symbols
        achievements = section_entry(sections, 4)
        first = list(ACHIEVEMENT.unpack_from(achievements[1]))
        first[12:17] = [0, len(maximum_program), 1, 0, 2048]
        record = ACHIEVEMENT.pack(*first)
        achievements[1] = bytearray(record * 128)
        achievements[2] = 128
        with self.assertRaisesRegex(PackError, "referenced bytecode bytes"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

        flags, profile_hash, sections = unpack_pack_sections(original)
        achievements = section_entry(sections, 4)
        first = list(ACHIEVEMENT.unpack_from(achievements[1]))
        first[15] = 256
        record = ACHIEVEMENT.pack(*first)
        achievements[1] = bytearray(record * 17)
        achievements[2] = 17
        with self.assertRaisesRegex(PackError, "aggregate VM state slots"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

        flags, profile_hash, sections = unpack_pack_sections(original)
        original_asset = ASSET.unpack_from(section_entry(sections, 8)[1])
        encoded = bytes((1, 0x80)) * 16384
        asset_data = section_entry(sections, 9)
        asset_data[1] = bytearray(encoded)
        asset_data[2] = 1
        asset_record = ASSET.pack(
            original_asset[0], 2, 3, 1, 0, 0, 0, len(encoded), len(encoded) // 2
        )
        assets = section_entry(sections, 8)
        assets[1] = bytearray(asset_record * 9)
        assets[2] = 9
        with self.assertRaisesRegex(PackError, "referenced stored asset bytes"):
            inspect_pack(rebuild_pack(flags, profile_hash, sections))

    def test_inspector_bounds_pattern_scans_per_symbol_and_in_aggregate(self) -> None:
        original = compile_profile(load_profile(SYNTHETIC)).data

        def pattern_pack(scan_size: int, copies: int) -> bytes:
            flags, profile_hash, sections = unpack_pack_sections(original)
            symbols = section_entry(sections, 3)
            records = [
                bytes(symbols[1][at : at + SYMBOL.size])
                for at in range(0, len(symbols[1]), SYMBOL.size)
            ]
            pattern_record = next(record for record in records if SYMBOL.unpack(record)[3] == 3)
            resolver_offset = SYMBOL.unpack(pattern_record)[7]
            resolvers = section_entry(sections, 5)
            struct.pack_into("<I", resolvers[1], resolver_offset + 4, scan_size)
            symbols[1] = bytearray(b"".join(records + [pattern_record] * (copies - 1)))
            symbols[2] = len(records) + copies - 1
            return rebuild_pack(flags, profile_hash, sections)

        with self.assertRaisesRegex(PackError, "pattern"):
            inspect_pack(pattern_pack(32 * 1024 * 1024 + 1, 1))
        with self.assertRaisesRegex(PackError, "aggregate pattern scan bytes"):
            inspect_pack(pattern_pack(24 * 1024 * 1024, 3))

    def test_vm_rejects_truncated_and_stateful_derived_programs(self) -> None:
        with self.assertRaises(BytecodeError):
            verify_bytecode(bytes((Op.CONST_BYTES, 4, 1, 2, Op.END)), 0)
        report = DiagnosticReport()
        expression = compile_expression(
            {"op": "add", "left": 2, "right": 3}, [], report, "$.expression"
        )
        self.assertTrue(report.ok)
        result = evaluate_bytecode(
            expression.code, [], 0, VmState.with_slots(0), expression.instructions, expression.maximum_stack
        )
        self.assertEqual(5, result.value)

    def test_vm_primes_edges_and_hit_count_before_observing_transitions(self) -> None:
        for op, frames, expected in (
            ("rising", [1, 0, 1], [False, False, True]),
            ("falling", [0, 1, 0], [False, False, True]),
        ):
            program = self._condition_program(
                {"op": op, "condition": {"op": "eq", "symbol": "flag", "value": 1}},
                ["flag"],
            )
            state = VmState.with_slots(program.state_slots)
            observed = [
                evaluate_bytecode(
                    program.code,
                    [SymbolState(current=value)],
                    index,
                    state,
                    program.instructions,
                    program.maximum_stack,
                ).condition
                for index, value in enumerate(frames)
            ]
            self.assertEqual(expected, observed, op)

        counter = self._condition_program(
            {
                "op": "hit_count",
                "count": 1,
                "condition": {"op": "eq", "symbol": "flag", "value": 1},
            },
            ["flag"],
        )
        state = VmState.with_slots(counter.state_slots)
        observed = [
            evaluate_bytecode(
                counter.code,
                [SymbolState(current=value)],
                index,
                state,
                counter.instructions,
                counter.maximum_stack,
            ).condition
            for index, value in enumerate((1, 0, 1))
        ]
        self.assertEqual([False, False, True], observed)

    def test_vm_sequence_primes_each_stage_from_the_current_frame(self) -> None:
        program = self._condition_program(
            {
                "op": "sequence",
                "conditions": [
                    {"op": "eq", "symbol": "first", "value": 1},
                    {"op": "eq", "symbol": "second", "value": 1},
                ],
            },
            ["first", "second"],
        )
        state = VmState.with_slots(program.state_slots)
        frames = ((1, 1), (0, 1), (1, 1), (1, 1), (1, 0), (1, 1))
        observed = [
            evaluate_bytecode(
                program.code,
                [SymbolState(current=first), SymbolState(current=second)],
                index,
                state,
                program.instructions,
                program.maximum_stack,
            ).condition
            for index, (first, second) in enumerate(frames)
        ]
        self.assertEqual([False, False, False, False, False, True], observed)

    def test_vm_pause_restores_slot_mutations_from_the_paused_evaluation(self) -> None:
        program = self._condition_program(
            {
                "op": "pause_if",
                "condition": {
                    "op": "rising",
                    "condition": {"op": "eq", "symbol": "event", "value": 1},
                },
                "pause": {"op": "eq", "symbol": "paused", "value": 1},
            },
            ["event", "paused"],
        )
        state = VmState.with_slots(program.state_slots)

        def evaluate(event: int, paused: int, at: int) -> bool:
            return evaluate_bytecode(
                program.code,
                [SymbolState(current=event), SymbolState(current=paused)],
                at,
                state,
                program.instructions,
                program.maximum_stack,
            ).condition

        self.assertFalse(evaluate(0, 0, 0))
        self.assertFalse(evaluate(1, 1, 1))
        self.assertTrue(state.paused)
        self.assertFalse(evaluate(1, 1, 2))
        self.assertTrue(evaluate(1, 0, 3))
        self.assertFalse(state.paused)

    def test_vm_rejects_non_finite_f32_arithmetic_results(self) -> None:
        report = DiagnosticReport()
        expression = compile_expression(
            {"op": "multiply", "left": 3.4e38, "right": 2.0}, [], report, "$.expression"
        )
        self.assertTrue(report.ok, report.format())
        with self.assertRaisesRegex(BytecodeError, "non-finite arithmetic result"):
            evaluate_bytecode(
                expression.code,
                [],
                0,
                VmState.with_slots(0),
                expression.instructions,
                expression.maximum_stack,
            )

    def test_derived_expression_nesting_is_bounded(self) -> None:
        expression: object = 1
        for _index in range(34):
            expression = {"op": "add", "left": expression, "right": 1}
        report = DiagnosticReport()
        self.assertIsNone(compile_expression(expression, [], report, "$.expression"))
        self.assertIn("E_EXPRESSION_NESTING", {item.code for item in report.errors})


class SimulationTests(unittest.TestCase):
    def test_mk7_coin_subset_has_exact_builds_and_safe_thresholds(self) -> None:
        loaded = load_profile(REPOSITORY / "profiles/mario-kart-7-eur-coins/profile.json")
        pack = inspect_pack(compile_profile(loaded).data)
        self.assertEqual({"2112", "3152"}, {b["applicationVersion"] for b in pack["builds"]})
        self.assertTrue(all(not b["compatible"] for b in pack["builds"]))
        results = run_profile_tests(loaded)
        self.assertEqual(10, len(results))
        self.assertTrue(all(result.passed for result in results), results)
        self.assertEqual(("coins_25",), results[2].unlocked)

    def test_all_embedded_scenarios_pass(self) -> None:
        results = run_profile_tests(load_profile(SYNTHETIC))
        self.assertEqual(5, len(results))
        self.assertTrue(all(result.passed for result in results))
        self.assertNotIn("no_healing", results[1].unlocked)
        self.assertEqual(3, results[0].progress["collector"])


class ToolTests(unittest.TestCase):
    def test_hardware_self_test_generator_produces_valid_probe_and_exact_profiles(self) -> None:
        generator = runpy.run_path(
            str(REPOSITORY / "profiles" / "hardware-self-test" / "generate.py")
        )
        probe = generator["make_profile"]("000400001234ABCD", "EUR", "0")
        self.assertEqual("sha256:" + "0" * 64, probe["game"]["builds"][0]["codeFingerprint"])
        exact = generator["make_profile"](
            "000400001234ABCD", "EUR", "0", "live-text-crc32-v1:00123000:89abcdef"
        )
        self.assertEqual(
            "live-text-crc32-v1:00123000:89ABCDEF",
            inspect_pack(compile_profile(exact).data)["builds"][0]["codeFingerprint"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = generator["write_profile"](
                exact, Path(temporary) / "profile.json"
            )
            results = run_profile_tests(load_profile(profile_path))
        self.assertEqual(("hardware_self_test",), results[0].unlocked)
        self.assertTrue(results[0].passed)

    def test_dump_search_and_diff_are_little_endian(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = root / "before.bin"
            after = root / "after.bin"
            before.write_bytes(struct.pack("<4H", 1, 20, 3, 4))
            after.write_bytes(struct.pack("<4H", 1, 25, 3, 2))
            searched = search_dump(before, value_type="u16", value="20", base_address=0x8000000, stride=2)
            self.assertEqual("0x08000002", searched["matches"][0]["address"])
            increased = diff_dumps(before, after, value_type="u16", mode="increased", stride=2)
            self.assertEqual([2], [item["offset"] for item in increased["matches"]])

    def test_trace_inspector_validates_crc_and_structure(self) -> None:
        sample = b"\x34\x12"
        read = READ_HEADER.pack(0x08001000, len(sample), 0) + sample
        frame = FRAME_HEADER.pack(b"FRAM", len(read), 100, 1, 0, zlib.crc32(read) & 0xFFFFFFFF) + read
        build_id = b"synthetic-eur-v1"
        trace = TRACE_HEADER.pack(
            b"AMTR", 1, 0, 0x000400000FF40A00, bytes(range(16)), 1, len(build_id), 0
        ) + build_id + frame
        inspected = inspect_trace(trace, include_frames=True)
        self.assertEqual(1, inspected["frameCount"])
        self.assertEqual("0x08001000", inspected["frames"][0]["reads"][0]["address"])
        damaged = bytearray(trace)
        damaged[-1] ^= 1
        with self.assertRaisesRegex(TraceError, "CRC"):
            inspect_trace(damaged)

    def test_ra_import_is_local_and_marks_unsupported_conditions_false(self) -> None:
        document, warnings = import_ra_document(
            {
                "game": "Example",
                "achievements": [
                    {"ID": 1, "Title": "Imported", "Description": "Test", "Points": 5, "MemAddr": "0xH1234=1"}
                ],
            }
        )
        self.assertTrue(warnings)
        self.assertEqual("imported", document["profile"]["integrity"])
        self.assertEqual({"op": "eq", "left": {"const": 0}, "right": 1}, document["achievements"][0]["trigger"])


class CliTests(unittest.TestCase):
    def _run(self, arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = cli_main(arguments)
        return result, output.getvalue(), error.getvalue()

    def test_profile_validate_test_build_and_pack_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_pack = Path(temporary) / "synthetic.amunpack"
            code, output, error = self._run(["profile", "validate", str(SYNTHETIC), "--json"])
            self.assertEqual(0, code, error)
            self.assertTrue(json.loads(output)["ok"])
            code, output, error = self._run(["profile", "test", str(SYNTHETIC), "--json"])
            self.assertEqual(0, code, error)
            self.assertEqual(5, json.loads(output)["scenarioCount"])
            code, output, error = self._run(
                ["profile", "build", str(SYNTHETIC), "-o", str(output_pack), "--json"]
            )
            self.assertEqual(0, code, error)
            self.assertTrue(output_pack.is_file())
            code, output, error = self._run(["pack", "inspect", str(output_pack), "--json"])
            self.assertEqual(0, code, error)
            self.assertEqual(14, len(json.loads(output)["achievements"]))

    def test_dump_trace_sim_and_import_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dump = root / "dump.bin"
            dump.write_bytes(struct.pack("<2I", 10, 20))
            code, output, error = self._run(
                ["dump", "search", str(dump), "--type", "u32", "--value", "20", "--stride", "4", "--json"]
            )
            self.assertEqual(0, code, error)
            self.assertEqual(1, json.loads(output)["matchCount"])

            code, output, error = self._run(["sim", "run", str(SYNTHETIC), "--json"])
            self.assertEqual(0, code, error)
            self.assertEqual(5, len(json.loads(output)["scenarios"]))

            ra = root / "ra.json"
            imported = root / "profile.json"
            ra.write_text(json.dumps({"game": "X", "achievements": []}), encoding="utf-8")
            code, output, error = self._run(["import-ra", str(ra), "-o", str(imported), "--json"])
            self.assertEqual(0, code, error)
            self.assertTrue(imported.is_file())
            self.assertIn("warning:", error)

    def test_trace_replay_forwards_to_cpp_simulator_without_a_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulator = root / "amun-sim.exe"
            trace = root / "session.amuntrace"
            pack = root / "game.amunpack"
            ledger = root / "replay.ledger"
            simulator.write_bytes(b"mock")
            trace.write_bytes(b"trace")
            pack.write_bytes(b"pack")
            completed = subprocess.CompletedProcess([], 7)
            with patch("compiler.replay.subprocess.run", return_value=completed) as launched:
                code, output, error = self._run(
                    [
                        "trace",
                        "replay",
                        str(trace),
                        str(pack),
                        "--ledger",
                        str(ledger),
                        "--simulator",
                        str(simulator),
                    ]
                )
            self.assertEqual(7, code)
            self.assertEqual("", output)
            self.assertEqual("", error)
            launched.assert_called_once_with(
                [
                    str(simulator.resolve()),
                    "--pack",
                    str(pack.resolve()),
                    "--trace",
                    str(trace.resolve()),
                    "--ledger",
                    str(ledger.resolve()),
                ],
                check=False,
                shell=False,
            )


if __name__ == "__main__":
    unittest.main()
