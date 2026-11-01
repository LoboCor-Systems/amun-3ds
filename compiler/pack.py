"""Deterministic compiler and strict inspector for AMUN 1.0/1.1 packs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Any
import zlib

from .diagnostics import CompilationFailed, DiagnosticReport
from .profile import (
    expression_symbol_references,
    LoadedProfile,
    load_profile,
    normalize_fingerprint,
    ordered_symbol_names,
    parse_pattern,
    validate_profile,
)
from .vm import (
    BytecodeError,
    CompiledCondition,
    SymbolState,
    VmState,
    compile_condition,
    compile_expression,
    disassemble,
    evaluate_bytecode,
    verify_bytecode,
)


HEADER = struct.Struct("<4sHHIIIHH16s")
SECTION = struct.Struct("<IIII")
MANIFEST = struct.Struct("<QIIIII")
BUILD = struct.Struct("<IIIIIB3x")
SYMBOL = struct.Struct("<IBBBBIiIHBBIHH")
ACHIEVEMENT = struct.Struct("<IIIIIIIIHBBIIIHHI")
ASSET = struct.Struct("<IBBBxHHIII")

assert HEADER.size == 40
assert SECTION.size == 16
assert MANIFEST.size == 28
assert BUILD.size == 24
assert SYMBOL.size == 32
assert ACHIEVEMENT.size == 56
assert ASSET.size == 24

PACK_MAJOR = 1
PACK_MINOR = 1
MAX_PACK_BYTES = 2 * 1024 * 1024
MAX_BUILDS = 64
MAX_ACHIEVEMENTS = 500
MAX_SYMBOLS = 1024
MAX_STRINGS = 8192
MAX_STRING_BYTES = 1024
MAX_REFERENCED_STRING_BYTES = 2 * 1024 * 1024
MAX_PREREQUISITES = 32
MAX_POINTER_DEPTH = 16
MAX_SIGNATURE_BYTES = 128
MAX_PATTERN_SCAN_BYTES = 32 * 1024 * 1024
MAX_TOTAL_PATTERN_SCAN_BYTES = 64 * 1024 * 1024
MAX_ASSETS = 128
MAX_ASSET_STORED = 256 * 1024
MAX_ASSET_DECODED = 32 * 1024
MAX_TOTAL_ASSET_DECODED = 512 * 1024
MAX_BYTECODE_BYTES = 256 * 1024
MAX_VM_STACK = 64
MAX_VM_STATE_SLOTS = 256
MAX_TOTAL_VM_STATE_SLOTS = 4096
MAX_INSTRUCTIONS_PER_ACHIEVEMENT = 2048

SECTION_NAMES = {
    1: "manifest",
    2: "builds",
    3: "symbols",
    4: "achievements",
    5: "resolvers",
    6: "bytecode",
    7: "strings",
    8: "assets",
    9: "asset_data",
}
VALUE_TYPES = {
    "bit": 0,
    "bool": 1,
    "u8": 2,
    "s8": 3,
    "u16": 4,
    "s16": 5,
    "u32": 6,
    "s32": 7,
    "f32": 8,
    "bytes": 9,
    "fixed_string": 10,
}
VALUE_TYPE_NAMES = {value: key for key, value in VALUE_TYPES.items()}
POLL_CLASSES = {"fast": 0, "normal": 1, "slow": 2, "static": 3}
POLL_CLASS_NAMES = {value: key for key, value in POLL_CLASSES.items()}
RESOLVER_KINDS = {
    "absolute": 0,
    "module_relative": 1,
    "pointer_chain": 2,
    "pattern": 3,
    "derived": 4,
}
RESOLVER_KIND_NAMES = {value: key for key, value in RESOLVER_KINDS.items()}
ASSET_KINDS = {"icon": 1, "sound": 2}
ASSET_KIND_NAMES = {value: key for key, value in ASSET_KINDS.items()}
ASSET_FORMATS = {"rgb565": 1, "rgba5551": 2, "pcm_u8": 3}
ASSET_FORMAT_NAMES = {value: key for key, value in ASSET_FORMATS.items()}
ASSET_COMPRESSIONS = {"none": 0, "byte_rle": 1}
ASSET_COMPRESSION_NAMES = {value: key for key, value in ASSET_COMPRESSIONS.items()}


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledPack:
    data: bytes
    profile_hash: bytes
    symbol_names: tuple[str, ...]
    achievement_ids: tuple[str, ...]
    asset_names: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class StringTable:
    def __init__(self) -> None:
        self.data = bytearray(b"\0")
        self.offsets: dict[str, int] = {"": 0}

    def add(self, value: str) -> int:
        if not isinstance(value, str):
            raise PackError("internal non-string passed to string table")
        if "\0" in value:
            raise PackError("string table values cannot contain NUL")
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_STRING_BYTES:
            raise PackError(f"string table value exceeds {MAX_STRING_BYTES} UTF-8 bytes")
        if value not in self.offsets:
            self.offsets[value] = len(self.data)
            self.data.extend(encoded)
            self.data.append(0)
        return self.offsets[value]


def canonical_source(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _coerce_loaded(
    profile: LoadedProfile | dict[str, Any] | str | os.PathLike[str],
    project_root: str | os.PathLike[str] | None,
) -> tuple[dict[str, Any], Path]:
    if isinstance(profile, LoadedProfile):
        return profile.document, profile.project_root
    if isinstance(profile, (str, os.PathLike)):
        loaded = load_profile(profile)
        return loaded.document, loaded.project_root
    if not isinstance(profile, dict):
        raise TypeError("profile must be a LoadedProfile, source object, or local path")
    return profile, Path(project_root or ".").expanduser().resolve()


def _inline_bytes(value: Any, path: str, report: DiagnosticReport) -> bytes | None:
    if isinstance(value, str):
        tokens = value.split()
        try:
            if not tokens or any(len(token) != 2 for token in tokens):
                raise ValueError
            return bytes(int(token, 16) for token in tokens)
        except ValueError:
            report.error("E_ASSET_DATA", path, "inline asset data must be space-separated hexadecimal bytes")
            return None
    if isinstance(value, list) and all(
        isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 255 for item in value
    ):
        return bytes(value)
    report.error("E_ASSET_DATA", path, "inline asset data must be hex text or a byte array")
    return None


def _read_asset_bytes(
    definition: dict[str, Any], project_root: Path, path: str, report: DiagnosticReport
) -> bytes | None:
    if "data" in definition:
        return _inline_bytes(definition["data"], path + ".data", report)
    raw_file = definition.get("file")
    if not isinstance(raw_file, str):
        return None
    unresolved = project_root / raw_file
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        report.error("E_ASSET_PATH", path + ".file", "asset path escapes the profile project")
        return None
    if unresolved.is_symlink() or not candidate.is_file():
        report.error("E_ASSET_PATH", path + ".file", f"asset is not a regular local file: {candidate}")
        return None
    try:
        return candidate.read_bytes()
    except OSError as error:
        report.error("E_ASSET_IO", path + ".file", f"cannot read asset: {error}")
        return None


def _rle_encode(data: bytes) -> bytes:
    output = bytearray()
    cursor = 0
    while cursor < len(data):
        value = data[cursor]
        count = 1
        while cursor + count < len(data) and data[cursor + count] == value and count < 255:
            count += 1
        output.extend((count, value))
        cursor += count
    return bytes(output)


def _rle_decode(data: bytes, expected_size: int) -> bytes:
    if len(data) % 2:
        raise PackError("byte-RLE stream has an odd stored size")
    output = bytearray()
    for cursor in range(0, len(data), 2):
        count, value = data[cursor], data[cursor + 1]
        if count == 0 or len(output) + count > expected_size:
            raise PackError("byte-RLE stream has an invalid run")
        output.extend(bytes((value,)) * count)
    if len(output) != expected_size:
        raise PackError("byte-RLE decoded size mismatch")
    return bytes(output)


@dataclass(frozen=True)
class _AssetBuild:
    name: str
    kind: int
    format: int
    compression: int
    width: int
    height: int
    decoded: bytes
    stored: bytes


def _compile_assets(
    document: dict[str, Any], project_root: Path, report: DiagnosticReport
) -> list[_AssetBuild]:
    raw_assets = document.get("assets", {})
    if not isinstance(raw_assets, dict):
        return []
    output: list[_AssetBuild] = []
    total_decoded = 0
    total_stored = 0
    for name in sorted(raw_assets):
        definition = raw_assets[name]
        if not isinstance(definition, dict):
            continue
        path = f"$.assets.{name}"
        decoded = _read_asset_bytes(definition, project_root, path, report)
        if decoded is None:
            continue
        kind_name = definition.get("kind")
        format_name = definition.get("format")
        compression_name = definition.get("compression", "none")
        kind = ASSET_KINDS.get(kind_name, 0)
        asset_format = ASSET_FORMATS.get(format_name, 0)
        compression = ASSET_COMPRESSIONS.get(compression_name, 0)
        raw_width = definition.get("width", 0) or 0
        raw_height = definition.get("height", 0) or 0
        width = raw_width if isinstance(raw_width, int) and not isinstance(raw_width, bool) else 0
        height = raw_height if isinstance(raw_height, int) and not isinstance(raw_height, bool) else 0
        if len(decoded) == 0 or len(decoded) > MAX_ASSET_DECODED:
            report.error(
                "E_ASSET_DECODED_LIMIT",
                path,
                f"decoded asset must contain 1 through {MAX_ASSET_DECODED} bytes",
            )
        if kind_name == "icon" and isinstance(width, int) and isinstance(height, int):
            expected = width * height * 2
            if len(decoded) != expected:
                report.error(
                    "E_ASSET_SIZE",
                    path,
                    f"icon contains {len(decoded)} bytes; {width}x{height} {format_name} requires {expected}",
                )
        stored = _rle_encode(decoded) if compression_name == "byte_rle" else decoded
        total_decoded += len(decoded)
        total_stored += len(stored)
        output.append(
            _AssetBuild(name, kind, asset_format, compression, width, height, decoded, stored)
        )
    if len(output) > MAX_ASSETS:
        report.error("E_ASSET_LIMIT", "$.assets", f"pack exceeds {MAX_ASSETS} assets")
    if total_stored > MAX_ASSET_STORED:
        report.error("E_ASSET_STORED_LIMIT", "$.assets", "stored asset data exceeds 256 KiB")
    if total_decoded > MAX_TOTAL_ASSET_DECODED:
        report.error("E_ASSET_TOTAL_LIMIT", "$.assets", "decoded asset data exceeds 512 KiB")
    return output


def compile_profile(
    profile: LoadedProfile | dict[str, Any] | str | os.PathLike[str],
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> CompiledPack:
    document, root = _coerce_loaded(profile, project_root)
    report = validate_profile(document)
    symbol_names = ordered_symbol_names(document, report)
    symbols_object = document.get("symbols", {})
    achievement_objects = document.get("achievements", [])

    derived_programs: dict[str, CompiledCondition] = {}
    if isinstance(symbols_object, dict):
        for name in symbol_names:
            definition = symbols_object.get(name)
            resolver = definition.get("resolver") if isinstance(definition, dict) else None
            if isinstance(resolver, dict) and resolver.get("kind") == "derived":
                compiled = compile_expression(
                    resolver.get("expression"),
                    symbol_names,
                    report,
                    f"$.symbols.{name}.resolver.expression",
                )
                if compiled is not None:
                    current_index = symbol_names.index(name)
                    referenced = {
                        dependency
                        for dependency, _suffix in expression_symbol_references(
                            resolver.get("expression")
                        )
                    }
                    dependencies = [
                        index
                        for index, dependency in enumerate(symbol_names)
                        if dependency != name and dependency in referenced
                    ]
                    if any(index >= current_index for index in dependencies):
                        report.error(
                            "E_DERIVED_ORDER",
                            f"$.symbols.{name}.resolver.expression",
                            "derived dependency was not ordered before its consumer",
                        )
                    derived_programs[name] = compiled

    achievement_programs: list[CompiledCondition | None] = []
    if isinstance(achievement_objects, list):
        for index, achievement in enumerate(achievement_objects):
            if isinstance(achievement, dict):
                achievement_programs.append(
                    compile_condition(
                        achievement.get("trigger"),
                        symbol_names,
                        report,
                        f"$.achievements[{index}].trigger",
                    )
                )
            else:
                achievement_programs.append(None)
    unavailable_symbols = [SymbolState(0, valid=False) for _name in symbol_names]
    for index, program in enumerate(achievement_programs):
        if program is None:
            continue
        path = f"$.achievements[{index}].trigger"
        if any(item.code == "E_UNCONDITIONAL_UNLOCK" and item.path == path for item in report.errors):
            continue
        try:
            initial = evaluate_bytecode(
                program.code,
                unavailable_symbols,
                0,
                VmState.with_slots(program.state_slots),
                program.instructions,
                max(program.maximum_stack, 1),
            )
        except BytecodeError:
            continue
        if initial.condition:
            report.error(
                "E_UNCONDITIONAL_UNLOCK",
                path,
                "achievement unlocks immediately from fresh VM state without reading a symbol",
                "Require an observed transition, counter, or positive monotonic duration.",
            )
    assets = _compile_assets(document, root, report)
    if not report.ok:
        raise CompilationFailed(report)

    strings = StringTable()
    resolver_bytes = bytearray()
    bytecode_bytes = bytearray()

    game = document["game"]
    metadata = document["profile"]
    manifest_bytes = MANIFEST.pack(
        int(game["titleId"], 16),
        strings.add(game["name"]),
        strings.add(metadata.get("version", "")),
        strings.add(metadata.get("license", "")),
        strings.add(metadata.get("provenance", "")),
        0,
    )

    build_bytes = bytearray()
    for build in game["builds"]:
        fingerprint = normalize_fingerprint(build["codeFingerprint"])
        if fingerprint is None:
            raise PackError("validated build fingerprint could not be normalized")
        build_bytes.extend(
            BUILD.pack(
                strings.add(build["id"]),
                strings.add(build.get("region", "")),
                strings.add(build.get("applicationVersion", "")),
                strings.add(build.get("updateVersion", "")),
                strings.add(fingerprint),
                1 if build.get("compatible", False) else 0,
            )
        )

    symbol_bytes = bytearray()
    required_minor = 0
    for name in symbol_names:
        definition = symbols_object[name]
        resolver = definition["resolver"]
        kind_name = resolver["kind"]
        address = 0
        module_offset = 0
        resolver_offset = len(resolver_bytes)
        resolver_size = 0
        pointer_depth = 0
        symbol_flags = 0
        derived_offset = 0
        derived_size = 0
        if kind_name == "absolute":
            address = int(resolver["address"], 0) if isinstance(resolver["address"], str) else int(resolver["address"])
        elif kind_name == "module_relative":
            module_offset = int(resolver["offset"], 0) if isinstance(resolver["offset"], str) else int(resolver["offset"])
        elif kind_name == "pointer_chain":
            if "address" in resolver:
                address = int(resolver["address"], 0) if isinstance(resolver["address"], str) else int(resolver["address"])
            else:
                module_offset = int(resolver["moduleOffset"], 0) if isinstance(resolver["moduleOffset"], str) else int(resolver["moduleOffset"])
            offsets = [int(item, 0) if isinstance(item, str) else int(item) for item in resolver["offsets"]]
            pointer_depth = len(offsets)
            payload = b"".join(struct.pack("<i", item) for item in offsets)
            if "xorMasks" in resolver:
                symbol_flags |= 1
                payload += b"".join(struct.pack("<I", int(item, 0) if isinstance(item, str) else item)
                                    for item in resolver["xorMasks"])
            if resolver.get("refresh", False):
                symbol_flags |= 2
            if symbol_flags or pointer_depth > 8:
                required_minor = 1
            resolver_bytes.extend(payload)
            resolver_size = len(payload)
        elif kind_name == "pattern":
            pattern_report = DiagnosticReport()
            pattern = parse_pattern(resolver["pattern"], "pattern", pattern_report)
            if pattern is None:
                raise PackError("validated pattern could not be encoded")
            pattern_data, pattern_mask = pattern
            scan_start = int(resolver["scanStart"], 0) if isinstance(resolver["scanStart"], str) else int(resolver["scanStart"])
            scan_size = int(resolver["scanSize"], 0) if isinstance(resolver["scanSize"], str) else int(resolver["scanSize"])
            result_offset = int(resolver.get("resultOffset", 0), 0) if isinstance(resolver.get("resultOffset", 0), str) else int(resolver.get("resultOffset", 0))
            payload = struct.pack("<IIiH2x", scan_start, scan_size, result_offset, len(pattern_data))
            payload += pattern_data + pattern_mask
            resolver_bytes.extend(payload)
            resolver_size = len(payload)
        elif kind_name == "derived":
            program = derived_programs[name]
            derived_offset = len(bytecode_bytes)
            bytecode_bytes.extend(program.code)
            derived_size = len(program.code)

        value_type = definition["type"]
        value_size = int(definition.get("size", 0) or 0)
        symbol_bytes.extend(
            SYMBOL.pack(
                strings.add(name),
                VALUE_TYPES[value_type],
                POLL_CLASSES[definition.get("poll", "normal")],
                RESOLVER_KINDS[kind_name],
                symbol_flags,
                address,
                module_offset,
                resolver_offset,
                resolver_size,
                pointer_depth,
                int(definition.get("bitIndex", 0)),
                derived_offset,
                derived_size,
                value_size,
            )
        )

    achievement_bytes = bytearray()
    achievement_ids: list[str] = []
    for index, achievement in enumerate(achievement_objects):
        program = achievement_programs[index]
        if program is None:
            raise PackError("validated achievement has no compiled condition")
        achievement_ids.append(achievement["id"])
        tags = achievement.get("tags", "")
        tags_text = ",".join(tags) if isinstance(tags, list) else tags
        prerequisites = ",".join(achievement.get("prerequisites", []))
        offsets = (
            strings.add(achievement["id"]),
            strings.add(achievement["title"]),
            strings.add(achievement["description"]),
            strings.add(achievement.get("author", "")),
            strings.add(achievement.get("category", "")),
            strings.add(tags_text),
            strings.add(achievement.get("icon", "")),
            strings.add(prerequisites),
        )
        metadata_flags = (1 if achievement.get("secret", False) else 0) | (
            2 if achievement.get("missable", False) else 0
        )
        prereq_min = int(achievement.get("prerequisiteMinCount", 0) or 0)
        prereq_list = achievement.get("prerequisites", [])
        if prereq_min < 0 or prereq_min > 255:
            raise PackError(f"achievement {achievement['id']} prerequisiteMinCount out of range")
        if prereq_min and prereq_min > len(prereq_list):
            raise PackError(
                f"achievement {achievement['id']} prerequisiteMinCount exceeds prerequisite list"
            )
        code_offset = len(bytecode_bytes)
        bytecode_bytes.extend(program.code)
        achievement_bytes.extend(
            ACHIEVEMENT.pack(
                *offsets,
                int(achievement.get("points", 0)),
                metadata_flags,
                prereq_min,
                program.progress_target,
                code_offset,
                len(program.code),
                program.maximum_stack,
                program.state_slots,
                program.instructions,
            )
        )

    asset_bytes = bytearray()
    asset_data = bytearray()
    for asset in assets:
        data_offset = len(asset_data)
        asset_data.extend(asset.stored)
        asset_bytes.extend(
            ASSET.pack(
                strings.add(asset.name),
                asset.kind,
                asset.format,
                asset.compression,
                asset.width,
                asset.height,
                data_offset,
                len(asset.stored),
                len(asset.decoded),
            )
        )

    sections: list[tuple[int, bytes, int]] = [
        (1, manifest_bytes, 1),
        (2, bytes(build_bytes), len(game["builds"])),
        (3, bytes(symbol_bytes), len(symbol_names)),
        (4, bytes(achievement_bytes), len(achievement_objects)),
        (5, bytes(resolver_bytes), sum(1 for name in symbol_names if symbols_object[name]["resolver"]["kind"] in {"pointer_chain", "pattern"})),
        (6, bytes(bytecode_bytes), len(derived_programs) + len(achievement_objects)),
        (7, bytes(strings.data), len(strings.offsets)),
    ]
    if assets:
        sections.extend(((8, bytes(asset_bytes), len(assets)), (9, bytes(asset_data), len(assets))))

    header_size = HEADER.size + SECTION.size * len(sections)
    cursor = header_size
    directory = bytearray()
    payload = bytearray()
    for section_type, data, count in sections:
        directory.extend(SECTION.pack(section_type, cursor, len(data), count))
        payload.extend(data)
        cursor += len(data)
    total_size = cursor
    if total_size > MAX_PACK_BYTES:
        limit_report = DiagnosticReport()
        limit_report.error("E_PACK_LIMIT", "$", f"compiled pack is {total_size} bytes; limit is {MAX_PACK_BYTES}")
        raise CompilationFailed(limit_report)
    profile_hash = hashlib.sha256(canonical_source(document)).digest()[:16]
    flags = 1 if assets else 0
    header = HEADER.pack(
        b"AMUN",
        PACK_MAJOR,
        required_minor,
        total_size,
        zlib.crc32(payload) & 0xFFFFFFFF,
        flags,
        len(sections),
        header_size,
        profile_hash,
    )
    result = bytes(header + directory + payload)
    # Inspect our own output through a separate parser before returning it.
    inspect_pack(result)
    return CompiledPack(
        result,
        profile_hash,
        tuple(symbol_names),
        tuple(achievement_ids),
        tuple(asset.name for asset in assets),
    )


def write_pack(compiled: CompiledPack, path: str | os.PathLike[str]) -> Path:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="w+b", dir=destination.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(compiled.data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _slice(data: bytes, offset: int, size: int, description: str) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise PackError(f"{description} is outside its section")
    return data[offset : offset + size]


def _string_reader(strings: bytes):
    if not strings or strings[0] != 0:
        raise PackError("string table must begin with NUL")

    def read(offset: int) -> str:
        if not 0 <= offset < len(strings):
            raise PackError(f"string offset {offset} is outside the string section")
        end = strings.find(
            b"\0", offset, min(len(strings), offset + MAX_STRING_BYTES + 1)
        )
        if end < 0:
            raise PackError(
                f"string at offset {offset} is unterminated or exceeds "
                f"{MAX_STRING_BYTES} bytes"
            )
        try:
            return strings[offset:end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise PackError(f"string at offset {offset} is not UTF-8") from error

    return read


def _load_pack_bytes(source: bytes | bytearray | memoryview | str | os.PathLike[str]) -> bytes:
    if isinstance(source, (str, os.PathLike)):
        path = Path(source).expanduser().resolve()
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_PACK_BYTES + 1)
            if len(data) > MAX_PACK_BYTES:
                raise PackError("pack exceeds 2 MiB safety limit")
            return data
        except OSError as error:
            raise PackError(f"cannot read pack {path}: {error}") from error
    source_size = source.nbytes if isinstance(source, memoryview) else len(source)
    if source_size > MAX_PACK_BYTES:
        raise PackError("pack exceeds 2 MiB safety limit")
    data = bytes(source)
    return data


def inspect_pack(source: bytes | bytearray | memoryview | str | os.PathLike[str]) -> dict[str, Any]:
    data = _load_pack_bytes(source)
    if len(data) < HEADER.size:
        raise PackError("pack has a truncated header")
    magic, major, minor, total_size, expected_crc, flags, section_count, header_size, profile_hash = HEADER.unpack_from(data)
    if magic != b"AMUN":
        raise PackError("expected AMUN magic")
    if major != PACK_MAJOR or minor > PACK_MINOR:
        raise PackError(f"unsupported pack version {major}.{minor}")
    if total_size != len(data):
        raise PackError("declared size differs from file size")
    if not 1 <= section_count <= 16 or header_size != HEADER.size + section_count * SECTION.size:
        raise PackError("invalid section directory size")
    if header_size > len(data):
        raise PackError("section directory exceeds file")
    actual_crc = zlib.crc32(data[header_size:]) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise PackError("payload CRC-32 mismatch")

    sections: dict[int, tuple[int, int, int]] = {}
    ranges: list[tuple[int, int]] = []
    section_output: list[dict[str, Any]] = []
    for index in range(section_count):
        section_type, offset, size, count = SECTION.unpack_from(data, HEADER.size + index * SECTION.size)
        if section_type in sections:
            raise PackError(f"duplicate section type {section_type}")
        if offset < header_size or offset + size > len(data):
            raise PackError(f"section {section_type} is outside payload")
        sections[section_type] = (offset, size, count)
        if size:
            ranges.append((offset, offset + size))
        section_output.append(
            {"type": section_type, "name": SECTION_NAMES.get(section_type, "unknown"), "offset": offset, "size": size, "count": count}
        )
    ranges.sort()
    if any(current[0] < previous[1] for previous, current in zip(ranges, ranges[1:])):
        raise PackError("pack sections overlap")
    if not set(range(1, 8)).issubset(sections):
        raise PackError("one or more required sections are absent")
    if (8 in sections) != (9 in sections):
        raise PackError("asset records and asset data must appear together")

    def section_data(section_type: int) -> bytes:
        offset, size, _count = sections[section_type]
        return data[offset : offset + size]

    manifest_data = section_data(1)
    builds_data = section_data(2)
    symbols_data = section_data(3)
    achievements_data = section_data(4)
    resolvers_data = section_data(5)
    bytecode_data = section_data(6)
    strings_data = section_data(7)
    if len(manifest_data) != MANIFEST.size or sections[1][2] != 1:
        raise PackError("invalid manifest section")
    if len(builds_data) != sections[2][2] * BUILD.size:
        raise PackError("build record count does not match section size")
    if len(symbols_data) != sections[3][2] * SYMBOL.size:
        raise PackError("symbol record count does not match section size")
    if len(achievements_data) != sections[4][2] * ACHIEVEMENT.size:
        raise PackError("achievement record count does not match section size")
    build_count = sections[2][2]
    symbol_count = sections[3][2]
    achievement_count = sections[4][2]
    if not 1 <= build_count <= MAX_BUILDS:
        raise PackError(f"build count must be 1 through {MAX_BUILDS}")
    if symbol_count > MAX_SYMBOLS:
        raise PackError(f"symbol count exceeds {MAX_SYMBOLS}")
    if not 1 <= achievement_count <= MAX_ACHIEVEMENTS:
        raise PackError(f"achievement count must be 1 through {MAX_ACHIEVEMENTS}")
    if len(bytecode_data) > MAX_BYTECODE_BYTES:
        raise PackError("bytecode section exceeds limit")
    if not strings_data or strings_data[0] != 0:
        raise PackError("string table must begin with NUL")
    actual_string_count = strings_data.count(b"\0")
    if sections[7][2] > MAX_STRINGS or actual_string_count != sections[7][2]:
        raise PackError("string table count exceeds limit or does not match data")

    raw_read_string = _string_reader(strings_data)
    referenced_string_bytes = 0

    def read_string(offset: int) -> str:
        nonlocal referenced_string_bytes
        value = raw_read_string(offset)
        referenced_string_bytes += len(value.encode("utf-8")) + 1
        if referenced_string_bytes > MAX_REFERENCED_STRING_BYTES:
            raise PackError("referenced string bytes exceed limit")
        return value

    title_id, name_offset, version_offset, license_offset, provenance_offset, _reserved = MANIFEST.unpack(manifest_data)
    manifest = {
        "titleId": f"{title_id:016X}",
        "gameName": read_string(name_offset),
        "profileVersion": read_string(version_offset),
        "license": read_string(license_offset),
        "provenance": read_string(provenance_offset),
    }

    builds: list[dict[str, Any]] = []
    for index in range(build_count):
        offsets = BUILD.unpack_from(builds_data, index * BUILD.size)
        fingerprint = read_string(offsets[4])
        if normalize_fingerprint(fingerprint) != fingerprint:
            raise PackError(f"build {index} has a non-canonical or unknown fingerprint scheme")
        builds.append(
            {
                "id": read_string(offsets[0]),
                "region": read_string(offsets[1]),
                "applicationVersion": read_string(offsets[2]),
                "updateVersion": read_string(offsets[3]),
                "codeFingerprint": fingerprint,
                "compatible": bool(offsets[5] & 1),
            }
        )

    symbols: list[dict[str, Any]] = []
    symbol_names: list[str] = []
    derived_ranges: list[tuple[int, int, int]] = []
    referenced_bytecode_bytes = 0
    total_pattern_scan_bytes = 0
    for index in range(symbol_count):
        fields = SYMBOL.unpack_from(symbols_data, index * SYMBOL.size)
        (
            name_at, value_type, poll_class, resolver_kind, symbol_flags, address,
            module_offset, resolver_offset, resolver_size, pointer_depth, bit_index,
            derived_offset, derived_size, value_size,
        ) = fields
        if value_type not in VALUE_TYPE_NAMES or poll_class not in POLL_CLASS_NAMES or resolver_kind not in RESOLVER_KIND_NAMES:
            raise PackError(f"symbol {index} has invalid enum value")
        if pointer_depth > MAX_POINTER_DEPTH or bit_index > 7:
            raise PackError(f"symbol {index} exceeds pointer/bit limits")
        if symbol_flags & ~3 or (symbol_flags and resolver_kind != 2):
            raise PackError("invalid pointer resolver flags")
        if minor == 0 and (symbol_flags or pointer_depth > 8):
            raise PackError("extended pointer resolver requires pack 1.1")
        fixed = value_type in (9, 10)
        if (fixed and not 1 <= value_size <= 16) or (not fixed and value_size != 0):
            raise PackError(f"symbol {index} has invalid value_size")
        resolver_payload = _slice(resolvers_data, resolver_offset, resolver_size, "resolver")
        resolver: dict[str, Any] = {"kind": RESOLVER_KIND_NAMES[resolver_kind]}
        if resolver_kind == 0:
            if resolver_size:
                raise PackError("absolute resolver unexpectedly has payload")
            resolver["address"] = f"0x{address:08X}"
        elif resolver_kind == 1:
            if resolver_size:
                raise PackError("module-relative resolver unexpectedly has payload")
            resolver["offset"] = module_offset
        elif resolver_kind == 2:
            expected_size = pointer_depth * 4 + ((pointer_depth - 1) * 4 if symbol_flags & 1 else 0)
            if not 1 <= pointer_depth <= MAX_POINTER_DEPTH or resolver_size != expected_size:
                raise PackError("pointer resolver size does not match depth")
            resolver["address"] = f"0x{address:08X}" if address else None
            resolver["moduleOffset"] = module_offset if not address else None
            resolver["offsets"] = list(struct.unpack_from("<" + "i" * pointer_depth, resolver_payload))
            if symbol_flags & 1:
                resolver["xorMasks"] = list(struct.unpack_from("<" + "I" * (pointer_depth - 1),
                                                               resolver_payload, pointer_depth * 4))
            if symbol_flags & 2:
                resolver["refresh"] = True
        elif resolver_kind == 3:
            if resolver_size < 18:
                raise PackError("pattern resolver is truncated")
            scan_start, scan_size, result_offset, pattern_length = struct.unpack_from("<IIiH", resolver_payload)
            if (
                not 1 <= pattern_length <= MAX_SIGNATURE_BYTES
                or resolver_size != 16 + pattern_length * 2
                or not pattern_length <= scan_size <= MAX_PATTERN_SCAN_BYTES
                or scan_start + scan_size > 0xFFFFFFFF
            ):
                raise PackError("pattern resolver has invalid length")
            total_pattern_scan_bytes += scan_size
            if total_pattern_scan_bytes > MAX_TOTAL_PATTERN_SCAN_BYTES:
                raise PackError("aggregate pattern scan bytes exceed limit")
            pattern = resolver_payload[16 : 16 + pattern_length]
            mask = resolver_payload[16 + pattern_length :]
            resolver.update(
                {
                    "scanStart": f"0x{scan_start:08X}",
                    "scanSize": scan_size,
                    "resultOffset": result_offset,
                    "pattern": " ".join(f"{byte:02X}" if mask_byte else "??" for byte, mask_byte in zip(pattern, mask)),
                }
            )
        elif resolver_size:
            raise PackError("derived resolver unexpectedly has resolver payload")
        name = read_string(name_at)
        if not name:
            raise PackError("symbol name is empty")
        symbol_names.append(name)
        derived_code = _slice(bytecode_data, derived_offset, derived_size, "derived bytecode")
        referenced_bytecode_bytes += derived_size
        if referenced_bytecode_bytes > MAX_BYTECODE_BYTES:
            raise PackError("referenced bytecode bytes exceed limit")
        if resolver_kind == 4:
            if not derived_code:
                raise PackError(f"derived symbol {name} has no bytecode")
            derived_ranges.append((index, derived_offset, derived_size))
        elif derived_size:
            raise PackError(f"non-derived symbol {name} has derived bytecode")
        symbols.append(
            {
                "name": name,
                "type": VALUE_TYPE_NAMES[value_type],
                "poll": POLL_CLASS_NAMES[poll_class],
                "flags": symbol_flags,
                "bitIndex": bit_index,
                "valueSize": value_size,
                "resolver": resolver,
                "derivedBytecode": {
                    "offset": derived_offset,
                    "size": derived_size,
                } if derived_size else None,
            }
        )

    for index, offset, size in derived_ranges:
        code = bytecode_data[offset : offset + size]
        try:
            info = verify_bytecode(code, symbol_count)
        except BytecodeError as error:
            raise PackError(f"invalid bytecode for derived symbol {symbols[index]['name']}: {error}") from error
        if info.state_slots:
            raise PackError(f"derived symbol {symbols[index]['name']} uses state slots")
        symbols[index]["derivedBytecode"].update(
            {
                "maxStack": info.maximum_stack,
                "stateSlots": info.state_slots,
                "instructions": info.instructions,
                "disassembly": disassemble(code, symbol_names),
            }
        )

    achievements: list[dict[str, Any]] = []
    total_vm_state_slots = 0
    for index in range(achievement_count):
        fields = ACHIEVEMENT.unpack_from(achievements_data, index * ACHIEVEMENT.size)
        string_offsets = fields[:8]
        points, metadata_flags, prerequisite_min_count, progress_target, code_offset, code_size, max_stack, state_slots, budget = fields[8:]
        strings = [read_string(offset) for offset in string_offsets]
        if not strings[0]:
            raise PackError(f"achievement {index} has an empty id")
        prerequisites = [item for item in strings[7].split(",") if item]
        if len(prerequisites) > MAX_PREREQUISITES:
            raise PackError(
                f"achievement {strings[0]} exceeds {MAX_PREREQUISITES} prerequisites"
            )
        if (
            points > 10000
            or not 1 <= max_stack <= MAX_VM_STACK
            or state_slots > MAX_VM_STATE_SLOTS
            or not 1 <= budget <= MAX_INSTRUCTIONS_PER_ACHIEVEMENT
        ):
            raise PackError(f"achievement {strings[0]} has invalid declared limits")
        code = _slice(bytecode_data, code_offset, code_size, "achievement bytecode")
        referenced_bytecode_bytes += code_size
        if referenced_bytecode_bytes > MAX_BYTECODE_BYTES:
            raise PackError("referenced bytecode bytes exceed limit")
        total_vm_state_slots += state_slots
        if total_vm_state_slots > MAX_TOTAL_VM_STATE_SLOTS:
            raise PackError("aggregate VM state slots exceed limit")
        try:
            info = verify_bytecode(code, len(symbols))
        except BytecodeError as error:
            raise PackError(f"invalid bytecode for achievement {strings[0]}: {error}") from error
        if max_stack < info.maximum_stack or state_slots < info.state_slots or budget < info.instructions:
            raise PackError(f"achievement {strings[0]} declares insufficient VM limits")
        achievements.append(
            {
                "id": strings[0],
                "title": strings[1],
                "description": strings[2],
                "author": strings[3],
                "category": strings[4],
                "tags": strings[5],
                "icon": strings[6],
                "prerequisites": prerequisites,
                "prerequisiteMinCount": prerequisite_min_count,
                "points": points,
                "secret": bool(metadata_flags & 1),
                "missable": bool(metadata_flags & 2),
                "progressTarget": progress_target,
                "bytecodeOffset": code_offset,
                "bytecodeSize": code_size,
                "maxStack": max_stack,
                "stateSlots": state_slots,
                "instructionBudget": budget,
                "verifiedInstructions": info.instructions,
                "disassembly": disassemble(code, symbol_names),
            }
        )

    assets: list[dict[str, Any]] = []
    if 8 in sections:
        asset_records = section_data(8)
        asset_data = section_data(9)
        if sections[8][2] > MAX_ASSETS or len(asset_records) != sections[8][2] * ASSET.size:
            raise PackError("asset records exceed count/size limits")
        if len(asset_data) > MAX_ASSET_STORED:
            raise PackError("stored asset data exceeds limit")
        total_decoded = 0
        total_stored_references = 0
        for index in range(sections[8][2]):
            name_at, kind, asset_format, compression, width, height, data_offset, stored_size, decoded_size = ASSET.unpack_from(asset_records, index * ASSET.size)
            name = read_string(name_at)
            if not name or kind not in ASSET_KIND_NAMES or asset_format not in ASSET_FORMAT_NAMES or compression not in ASSET_COMPRESSION_NAMES:
                raise PackError(f"asset {index} has invalid name or enum")
            if not 1 <= decoded_size <= MAX_ASSET_DECODED or stored_size == 0:
                raise PackError(f"asset {name} has invalid size")
            stored = _slice(asset_data, data_offset, stored_size, "asset data")
            total_stored_references += stored_size
            if total_stored_references > MAX_ASSET_STORED:
                raise PackError("referenced stored asset bytes exceed limit")
            decoded = stored if compression == 0 else _rle_decode(stored, decoded_size)
            if compression == 0 and stored_size != decoded_size:
                raise PackError(f"uncompressed asset {name} size mismatch")
            if kind == 1:
                if not 1 <= width <= 64 or not 1 <= height <= 64 or asset_format not in (1, 2) or decoded_size != width * height * 2:
                    raise PackError(f"icon asset {name} has invalid dimensions/format")
            elif width != 0 or height != 0 or asset_format != 3:
                raise PackError(f"sound asset {name} has invalid metadata")
            total_decoded += len(decoded)
            if total_decoded > MAX_TOTAL_ASSET_DECODED:
                raise PackError("total decoded assets exceed limit")
            assets.append(
                {
                    "name": name,
                    "kind": ASSET_KIND_NAMES[kind],
                    "format": ASSET_FORMAT_NAMES[asset_format],
                    "compression": ASSET_COMPRESSION_NAMES[compression],
                    "width": width,
                    "height": height,
                    "storedSize": stored_size,
                    "decodedSize": decoded_size,
                    "sha256": hashlib.sha256(decoded).hexdigest(),
                }
            )
    icon_names = {asset["name"] for asset in assets if asset["kind"] == "icon"}
    for achievement in achievements:
        if achievement["icon"] and achievement["icon"] not in icon_names:
            raise PackError(
                f"achievement {achievement['id']} references missing icon {achievement['icon']}"
            )

    return {
        "format": "AMUN",
        "version": f"{major}.{minor}",
        "totalSize": total_size,
        "headerSize": header_size,
        "flags": flags,
        "crc32": f"{expected_crc:08X}",
        "profileHash": profile_hash.hex(),
        "sections": section_output,
        "manifest": manifest,
        "builds": builds,
        "symbols": symbols,
        "achievements": achievements,
        "assets": assets,
    }
