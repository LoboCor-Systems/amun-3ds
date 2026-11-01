"""AMUN source-profile discovery, JSON loading, and semantic validation."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
import math
import os
from pathlib import Path
import re
import struct
from typing import Any, Iterable

from .diagnostics import DiagnosticReport


PROFILE_FILENAMES = ("profile.json", "game.json", "amun.json")
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
TITLE_ID = re.compile(r"^[0-9A-Fa-f]{16}$")
SHA256_FINGERPRINT = re.compile(r"^sha256:([0-9A-Fa-f]{64})$")
LIVE_TEXT_FINGERPRINT = re.compile(
    r"^live-text-crc32-v1:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})$"
)
VALUE_TYPES = {
    "bit", "bool", "u8", "s8", "u16", "s16", "u32", "s32", "f32", "bytes", "fixed_string"
}
POLL_CLASSES = {"fast", "normal", "slow", "static"}
RESOLVER_KINDS = {"absolute", "module_relative", "pointer_chain", "pattern", "derived"}
MAX_STRING_BYTES = 1024
MAX_SYMBOLS = 1024
MAX_ACHIEVEMENTS = 500
MAX_ASSETS = 128


class ProfileLoadError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedProfile:
    document: dict[str, Any]
    profile_path: Path
    project_root: Path


def normalize_fingerprint(value: Any) -> str | None:
    """Return the exact runtime comparison string for a known fingerprint scheme."""

    if not isinstance(value, str):
        return None
    sha256 = SHA256_FINGERPRINT.fullmatch(value)
    if sha256 is not None:
        return "sha256:" + sha256.group(1).lower()
    live_text = LIVE_TEXT_FINGERPRINT.fullmatch(value)
    if live_text is not None:
        text_size = int(live_text.group(1), 16)
        if not 1 <= text_size <= 32 * 1024 * 1024:
            return None
        # The 3DS identity adapter uses snprintf("%08X") for both fields.
        return f"live-text-crc32-v1:{live_text.group(1).upper()}:{live_text.group(2).upper()}"
    return None


def _profile_in_directory(directory: Path) -> Path:
    for filename in PROFILE_FILENAMES:
        path = directory / filename
        if path.is_file():
            return path
    json_files = sorted(path for path in directory.glob("*.json") if path.is_file())
    if len(json_files) == 1:
        return json_files[0]
    if not json_files:
        raise ProfileLoadError(
            f"no profile JSON in {directory}; expected one of {', '.join(PROFILE_FILENAMES)}"
        )
    raise ProfileLoadError(
        f"multiple root JSON files in {directory}; pass the source profile file explicitly"
    )


def load_profile(path: str | os.PathLike[str]) -> LoadedProfile:
    selected = Path(path).expanduser().resolve()
    if selected.is_dir():
        profile_path = _profile_in_directory(selected)
        project_root = selected
    elif selected.is_file():
        profile_path = selected
        project_root = selected.parent
    else:
        raise ProfileLoadError(f"profile path does not exist: {selected}")
    try:
        raw = profile_path.read_text(encoding="utf-8-sig")
        document = json.loads(raw)
    except OSError as error:
        raise ProfileLoadError(f"cannot read {profile_path}: {error}") from error
    except UnicodeError as error:
        raise ProfileLoadError(f"profile is not valid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise ProfileLoadError(
            f"invalid JSON at {profile_path}:{error.lineno}:{error.colno}: {error.msg}"
        ) from error
    if not isinstance(document, dict):
        raise ProfileLoadError("profile root must be a JSON object")
    return LoadedProfile(document, profile_path, project_root)


def parse_u32(value: Any, path: str, report: DiagnosticReport, *, allow_zero: bool = True) -> int | None:
    if isinstance(value, bool):
        report.error("E_INTEGER", path, "expected a 32-bit integer, not a Boolean")
        return None
    try:
        parsed = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        report.error("E_INTEGER", path, "expected a decimal integer or 0x-prefixed address")
        return None
    if parsed < (0 if allow_zero else 1) or parsed > 0xFFFFFFFF:
        report.error("E_U32_RANGE", path, "value is outside the unsigned 32-bit range")
        return None
    return parsed


def parse_i32(value: Any, path: str, report: DiagnosticReport) -> int | None:
    if isinstance(value, bool):
        report.error("E_INTEGER", path, "expected a signed 32-bit integer, not a Boolean")
        return None
    try:
        parsed = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        report.error("E_INTEGER", path, "expected a signed integer")
        return None
    if not -0x80000000 <= parsed <= 0x7FFFFFFF:
        report.error("E_I32_RANGE", path, "value is outside the signed 32-bit range")
        return None
    return parsed


def _string(
    value: Any,
    path: str,
    report: DiagnosticReport,
    *,
    required: bool = False,
    identifier: bool = False,
) -> str | None:
    if not isinstance(value, str):
        report.error("E_STRING", path, "expected a string")
        return None
    if required and not value:
        report.error("E_REQUIRED", path, "string cannot be empty")
    if "\x00" in value:
        report.error("E_NUL_STRING", path, "strings cannot contain NUL bytes")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        report.error("E_STRING_LIMIT", path, f"UTF-8 string exceeds {MAX_STRING_BYTES} bytes")
    if identifier and value and not IDENTIFIER.fullmatch(value):
        report.error(
            "E_IDENTIFIER",
            path,
            "identifier must start with a letter and contain only letters, digits, '.', '_', or '-'",
        )
    return value


def _validate_builds(game: dict[str, Any], report: DiagnosticReport) -> None:
    builds = game.get("builds")
    if not isinstance(builds, list) or not builds:
        report.error("E_BUILDS", "$.game.builds", "at least one exact supported build is required")
        return
    seen: set[str] = set()
    for index, raw_build in enumerate(builds):
        path = f"$.game.builds[{index}]"
        if not isinstance(raw_build, dict):
            report.error("E_OBJECT", path, "build must be an object")
            continue
        build_id = _string(raw_build.get("id"), path + ".id", report, required=True, identifier=True)
        if build_id in seen:
            report.error("E_DUPLICATE_ID", path + ".id", f"duplicate build id {build_id!r}")
        if build_id:
            seen.add(build_id)
        for field in ("region", "applicationVersion", "updateVersion"):
            _string(raw_build.get(field, ""), f"{path}.{field}", report)
        fingerprint = _string(
            raw_build.get("codeFingerprint"), path + ".codeFingerprint", report, required=True
        )
        if fingerprint is not None and normalize_fingerprint(fingerprint) is None:
            report.error(
                "E_EXACT_FINGERPRINT",
                path + ".codeFingerprint",
                "fingerprint must use sha256:<64 hex> or live-text-crc32-v1:<8 hex size>:<8 hex CRC>",
                "Use the exact scheme emitted by the identity tool; legacy bare hashes are rejected.",
            )
        compatible = raw_build.get("compatible", False)
        if not isinstance(compatible, bool):
            report.error("E_BOOLEAN", path + ".compatible", "compatible must be true or false")


def parse_pattern(value: Any, path: str, report: DiagnosticReport) -> tuple[bytes, bytes] | None:
    if not isinstance(value, str):
        report.error("E_PATTERN", path, "pattern must be a space-separated byte string")
        return None
    tokens = value.split()
    if not 1 <= len(tokens) <= 128:
        report.error("E_PATTERN_LIMIT", path, "pattern must contain 1 to 128 bytes")
        return None
    output = bytearray()
    mask = bytearray()
    for index, token in enumerate(tokens):
        if token in {"?", "??", "**"}:
            output.append(0)
            mask.append(0)
            continue
        if not re.fullmatch(r"[0-9A-Fa-f]{2}", token):
            report.error("E_PATTERN_BYTE", f"{path}[{index}]", f"invalid byte token {token!r}")
            return None
        output.append(int(token, 16))
        mask.append(0xFF)
    return bytes(output), bytes(mask)


def _validate_resolver(raw: Any, path: str, report: DiagnosticReport) -> None:
    if not isinstance(raw, dict):
        report.error("E_RESOLVER", path, "resolver must be an object")
        return
    kind = raw.get("kind")
    if kind != "pointer_chain" and ("xorMasks" in raw or "refresh" in raw):
        report.error("E_POINTER_OPTIONS", path, "xorMasks and refresh require pointer_chain")
    if kind not in RESOLVER_KINDS:
        report.error("E_RESOLVER_KIND", path + ".kind", f"unsupported resolver kind {kind!r}")
        return
    if kind == "derived":
        if "expression" not in raw:
            report.error(
                "E_DERIVED_EXPRESSION",
                path + ".expression",
                "derived resolver requires a bounded expression",
            )
    elif kind == "absolute":
        parse_u32(raw.get("address"), path + ".address", report, allow_zero=False)
    elif kind == "module_relative":
        parse_i32(raw.get("offset"), path + ".offset", report)
    elif kind == "pointer_chain":
        has_address = "address" in raw
        has_module = "moduleOffset" in raw
        if has_address == has_module:
            report.error(
                "E_POINTER_BASE",
                path,
                "pointer_chain requires exactly one of address or moduleOffset",
            )
        elif has_address:
            parse_u32(raw.get("address"), path + ".address", report, allow_zero=False)
        else:
            parse_i32(raw.get("moduleOffset"), path + ".moduleOffset", report)
        offsets = raw.get("offsets")
        if not isinstance(offsets, list) or not 1 <= len(offsets) <= 16:
            report.error("E_POINTER_DEPTH", path + ".offsets", "pointer offsets must contain 1 to 16 entries")
        else:
            for index, offset in enumerate(offsets):
                parse_i32(offset, f"{path}.offsets[{index}]", report)
        if "xorMasks" in raw:
            masks = raw["xorMasks"]
            if (not isinstance(masks, list) or not isinstance(offsets, list) or
                    len(masks) != len(offsets) - 1):
                report.error("E_POINTER_MASKS", path + ".xorMasks", "one XOR mask is required per dereference")
            else:
                for index, mask in enumerate(masks):
                    parse_u32(mask, f"{path}.xorMasks[{index}]", report)
        if not isinstance(raw.get("refresh", False), bool):
            report.error("E_BOOLEAN", path + ".refresh", "refresh must be true or false")
    elif kind == "pattern":
        parse_u32(raw.get("scanStart"), path + ".scanStart", report, allow_zero=False)
        parse_u32(raw.get("scanSize"), path + ".scanSize", report, allow_zero=False)
        parse_i32(raw.get("resultOffset", 0), path + ".resultOffset", report)
        parse_pattern(raw.get("pattern"), path + ".pattern", report)


def _validate_symbols(document: dict[str, Any], report: DiagnosticReport) -> set[str]:
    symbols = document.get("symbols")
    if not isinstance(symbols, dict):
        report.error("E_SYMBOLS", "$.symbols", "symbols must be an object keyed by stable symbol id")
        return set()
    if len(symbols) > MAX_SYMBOLS:
        report.error("E_SYMBOL_LIMIT", "$.symbols", f"profile exceeds the {MAX_SYMBOLS} symbol limit")
    names: set[str] = set()
    for name, raw_symbol in symbols.items():
        path = f"$.symbols.{name}"
        _string(name, path, report, required=True, identifier=True)
        names.add(name)
        if not isinstance(raw_symbol, dict):
            report.error("E_OBJECT", path, "symbol definition must be an object")
            continue
        value_type = raw_symbol.get("type")
        if value_type not in VALUE_TYPES:
            report.error("E_VALUE_TYPE", path + ".type", f"unsupported runtime value type {value_type!r}")
        poll = raw_symbol.get("poll", "normal")
        if poll not in POLL_CLASSES:
            report.error("E_POLL_CLASS", path + ".poll", f"unsupported polling class {poll!r}")
        bit_index = raw_symbol.get("bitIndex", 0)
        if not isinstance(bit_index, int) or isinstance(bit_index, bool) or not 0 <= bit_index <= 7:
            report.error("E_BIT_INDEX", path + ".bitIndex", "bitIndex must be an integer from 0 through 7")
        value_size = raw_symbol.get("size", 0)
        fixed = value_type in {"bytes", "fixed_string"}
        if fixed:
            if not isinstance(value_size, int) or isinstance(value_size, bool) or not 1 <= value_size <= 16:
                report.error(
                    "E_VALUE_SIZE",
                    path + ".size",
                    "bytes and fixed_string symbols require size from 1 through 16",
                )
        elif value_size not in (0, None):
            report.error("E_VALUE_SIZE", path + ".size", "size is valid only for bytes/fixed_string symbols")
        _validate_resolver(raw_symbol.get("resolver"), path + ".resolver", report)
    return names


def _walk_condition_symbols(value: Any) -> Iterable[tuple[str, str]]:
    """Find explicit condition symbol references without recursive Python calls."""

    pending: list[tuple[Any, str]] = [(value, "")]
    while pending:
        current, suffix = pending.pop()
        if isinstance(current, dict):
            symbol = current.get("symbol")
            if isinstance(symbol, str):
                yield symbol, suffix + ".symbol"
            for key, child in reversed(tuple(current.items())):
                if key != "symbol":
                    pending.append((child, suffix + f".{key}"))
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                pending.append((current[index], suffix + f"[{index}]"))


def _literal_boolean_condition(value: Any, depth: int = 0) -> bool | None:
    """Evaluate only literal Boolean groups; return ``None`` for dynamic logic."""

    if depth > 32:
        return None
    if isinstance(value, bool):
        return value
    if not isinstance(value, dict):
        return None
    if "all" in value and "op" not in value:
        operation, children = "all", value.get("all")
    elif "any" in value and "op" not in value:
        operation, children = "any", value.get("any")
    elif "not" in value and "op" not in value:
        child = _literal_boolean_condition(value.get("not"), depth + 1)
        return None if child is None else not child
    else:
        operation = str(value.get("op", "")).strip().lower().replace("-", "_")
        children = value.get("conditions")
        if operation == "not":
            child = _literal_boolean_condition(value.get("condition"), depth + 1)
            return None if child is None else not child
    if operation not in {"all", "any"} or not isinstance(children, list) or not children:
        return None
    resolved = [_literal_boolean_condition(child, depth + 1) for child in children]
    if operation == "all":
        if False in resolved:
            return False
        return True if all(item is True for item in resolved) else None
    if True in resolved:
        return True
    return False if all(item is False for item in resolved) else None


def expression_symbol_references(value: Any) -> Iterable[tuple[str, str]]:
    """Yield symbol references from the bounded value-expression grammar.

    Bare strings are shorthand for current-value symbol loads. Text and byte
    constants live under dedicated ``string``/``bytes`` keys and are therefore
    deliberately not traversed.
    """

    pending: list[tuple[Any, str]] = [(value, "")]
    while pending:
        current, suffix = pending.pop()
        if isinstance(current, str):
            yield current, suffix
            continue
        if not isinstance(current, dict):
            continue
        if "symbol" in current:
            symbol = current.get("symbol")
            if isinstance(symbol, str):
                yield symbol, suffix + ".symbol"
            continue
        if "op" in current:
            pending.append((current.get("right"), suffix + ".right"))
            pending.append((current.get("left"), suffix + ".left"))


def ordered_symbol_names(
    document: dict[str, Any], report: DiagnosticReport | None = None
) -> list[str]:
    """Return a stable dependency-first order and diagnose derived cycles."""

    symbols = document.get("symbols")
    if not isinstance(symbols, dict):
        return []
    graph: dict[str, set[str]] = {str(name): set() for name in symbols}
    for name, definition in symbols.items():
        if not isinstance(definition, dict):
            continue
        resolver = definition.get("resolver")
        if not isinstance(resolver, dict) or resolver.get("kind") != "derived":
            continue
        expression = resolver.get("expression")
        for dependency, suffix in expression_symbol_references(expression):
            if dependency not in graph:
                if report is not None:
                    report.error(
                        "E_UNKNOWN_SYMBOL",
                        f"$.symbols.{name}.resolver.expression{suffix}",
                        f"derived expression references unknown symbol {dependency!r}",
                    )
            else:
                graph[str(name)].add(dependency)

    dependency_count = {name: len(dependencies) for name, dependencies in graph.items()}
    dependents: dict[str, list[str]] = {name: [] for name in graph}
    for consumer, dependencies in graph.items():
        for dependency in dependencies:
            dependents[dependency].append(consumer)
    ready = [name for name, count in dependency_count.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        name = heapq.heappop(ready)
        ordered.append(name)
        for consumer in sorted(dependents[name]):
            dependency_count[consumer] -= 1
            if dependency_count[consumer] == 0:
                heapq.heappush(ready, consumer)
    if len(ordered) != len(graph):
        blocked = sorted(name for name in graph if dependency_count[name] > 0)
        if report is not None:
            report.error(
                "E_DERIVED_CYCLE",
                f"$.symbols.{blocked[0]}.resolver.expression",
                "derived dependency cycle prevents ordering: " + ", ".join(blocked),
            )
        # Compilation will fail, but retaining every name permits additional
        # independent diagnostics to be reported in the same validation pass.
        ordered.extend(blocked)
    return ordered


def _validate_achievements(
    document: dict[str, Any], symbol_names: set[str], icon_names: set[str], report: DiagnosticReport
) -> set[str]:
    achievements = document.get("achievements")
    if not isinstance(achievements, list) or not achievements:
        report.error("E_ACHIEVEMENTS", "$.achievements", "at least one achievement is required")
        return set()
    if len(achievements) > MAX_ACHIEVEMENTS:
        report.error(
            "E_ACHIEVEMENT_LIMIT",
            "$.achievements",
            f"profile exceeds the {MAX_ACHIEVEMENTS} achievement limit",
        )
    ids: set[str] = set()
    prerequisites: dict[str, list[str]] = {}
    for index, raw_achievement in enumerate(achievements):
        path = f"$.achievements[{index}]"
        if not isinstance(raw_achievement, dict):
            report.error("E_OBJECT", path, "achievement must be an object")
            continue
        achievement_id = _string(
            raw_achievement.get("id"), path + ".id", report, required=True, identifier=True
        )
        if achievement_id in ids:
            report.error("E_DUPLICATE_ID", path + ".id", f"duplicate achievement id {achievement_id!r}")
        if achievement_id:
            ids.add(achievement_id)
        for field in ("title", "description"):
            _string(raw_achievement.get(field), f"{path}.{field}", report, required=True)
        for field in ("author", "category", "icon"):
            _string(raw_achievement.get(field, ""), f"{path}.{field}", report)
        icon = raw_achievement.get("icon", "")
        if isinstance(icon, str) and icon and icon not in icon_names:
            report.error(
                "E_UNKNOWN_ICON",
                path + ".icon",
                f"achievement references missing icon asset {icon!r}",
            )
        tags = raw_achievement.get("tags", [])
        if isinstance(tags, list):
            for tag_index, tag in enumerate(tags):
                _string(tag, f"{path}.tags[{tag_index}]", report)
        elif isinstance(tags, str):
            _string(tags, path + ".tags", report)
        else:
            report.error("E_TAGS", path + ".tags", "tags must be a string or string array")
        points = raw_achievement.get("points", 0)
        if not isinstance(points, int) or isinstance(points, bool) or not 0 <= points <= 10000:
            report.error("E_POINTS", path + ".points", "points must be an integer from 0 through 10000")
        for flag in ("secret", "missable"):
            if not isinstance(raw_achievement.get(flag, False), bool):
                report.error("E_BOOLEAN", f"{path}.{flag}", f"{flag} must be true or false")
        raw_prerequisites = raw_achievement.get("prerequisites", [])
        if not isinstance(raw_prerequisites, list) or not all(
            isinstance(item, str) for item in raw_prerequisites
        ):
            report.error("E_PREREQUISITES", path + ".prerequisites", "prerequisites must be a string array")
            raw_prerequisites = []
        if len(set(raw_prerequisites)) != len(raw_prerequisites):
            report.error("E_DUPLICATE_PREREQUISITE", path + ".prerequisites", "prerequisites must be unique")
        raw_prereq_min = raw_achievement.get("prerequisiteMinCount", 0)
        if raw_prereq_min is None:
            raw_prereq_min = 0
        if not isinstance(raw_prereq_min, int) or isinstance(raw_prereq_min, bool) or raw_prereq_min < 0 or raw_prereq_min > 255:
            report.error(
                "E_PREREQUISITE_MIN",
                path + ".prerequisiteMinCount",
                "prerequisiteMinCount must be an integer 0-255",
            )
            raw_prereq_min = 0
        if raw_prereq_min and raw_prereq_min > len(raw_prerequisites):
            report.error(
                "E_PREREQUISITE_MIN",
                path + ".prerequisiteMinCount",
                "prerequisiteMinCount exceeds prerequisites length",
            )
        if achievement_id:
            prerequisites[achievement_id] = list(raw_prerequisites)
        trigger = raw_achievement.get("trigger")
        if not isinstance(trigger, (dict, bool)):
            report.error("E_TRIGGER", path + ".trigger", "trigger must be a condition object or Boolean")
        else:
            if _literal_boolean_condition(trigger) is True:
                report.error(
                    "E_UNCONDITIONAL_UNLOCK",
                    path + ".trigger",
                    "achievement is immediately true without observing an event or elapsed duration",
                    "Use a real condition; hardware self-tests may use a bounded duration over true.",
                )
            for symbol, suffix in _walk_condition_symbols(trigger):
                if symbol not in symbol_names:
                    report.error(
                        "E_UNKNOWN_SYMBOL",
                        path + ".trigger" + suffix,
                        f"condition references unknown symbol {symbol!r}",
                    )

    for owner, required in prerequisites.items():
        for prerequisite in required:
            if prerequisite not in ids:
                report.error(
                    "E_UNKNOWN_PREREQUISITE",
                    f"$.achievements[{owner}].prerequisites",
                    f"unknown prerequisite {prerequisite!r}",
                )
            elif prerequisite == owner:
                report.error(
                    "E_PREREQUISITE_CYCLE",
                    f"$.achievements[{owner}].prerequisites",
                    "achievement cannot require itself",
                )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visited:
            return
        if identifier in visiting:
            report.error(
                "E_PREREQUISITE_CYCLE",
                "$.achievements",
                f"prerequisite cycle includes {identifier!r}",
            )
            return
        visiting.add(identifier)
        for dependency in prerequisites.get(identifier, []):
            if dependency in prerequisites:
                visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in prerequisites:
        visit(identifier)
    return ids


def _validate_assets(document: dict[str, Any], report: DiagnosticReport) -> set[str]:
    assets = document.get("assets", {})
    if not isinstance(assets, dict):
        report.error("E_ASSETS", "$.assets", "assets must be an object keyed by stable asset name")
        return set()
    if len(assets) > MAX_ASSETS:
        report.error("E_ASSET_LIMIT", "$.assets", f"profile exceeds the {MAX_ASSETS} asset limit")
    icons: set[str] = set()
    for name, asset in assets.items():
        path = f"$.assets.{name}"
        _string(name, path, report, required=True, identifier=True)
        if not isinstance(asset, dict):
            report.error("E_OBJECT", path, "asset definition must be an object")
            continue
        kind = asset.get("kind")
        asset_format = asset.get("format")
        if kind == "icon":
            icons.add(name)
            if asset_format not in {"rgb565", "rgba5551"}:
                report.error("E_ASSET_FORMAT", path + ".format", "icon format must be rgb565 or rgba5551")
            for field in ("width", "height"):
                dimension = asset.get(field)
                if not isinstance(dimension, int) or isinstance(dimension, bool) or not 1 <= dimension <= 64:
                    report.error("E_ASSET_DIMENSION", f"{path}.{field}", "icon dimensions must be 1 through 64")
        elif kind == "sound":
            if asset_format != "pcm_u8":
                report.error("E_ASSET_FORMAT", path + ".format", "sound format must be pcm_u8")
            if asset.get("width", 0) not in (0, None) or asset.get("height", 0) not in (0, None):
                report.error("E_ASSET_DIMENSION", path, "sound assets cannot declare dimensions")
        else:
            report.error("E_ASSET_KIND", path + ".kind", "asset kind must be icon or sound")
        if asset.get("compression", "none") not in {"none", "byte_rle"}:
            report.error("E_ASSET_COMPRESSION", path + ".compression", "compression must be none or byte_rle")
        sources = [field for field in ("file", "data") if field in asset]
        if len(sources) != 1:
            report.error("E_ASSET_SOURCE", path, "asset requires exactly one of file or data")
        elif sources[0] == "file":
            _string(asset.get("file"), path + ".file", report, required=True)
        else:
            data = asset.get("data")
            if not isinstance(data, (str, list)):
                report.error("E_ASSET_SOURCE", path + ".data", "inline data must be hex text or a byte array")
    return icons


def _validate_test_value(
    value: Any,
    definition: dict[str, Any],
    path: str,
    report: DiagnosticReport,
) -> None:
    value_type = definition.get("type")
    if value_type == "f32":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            report.error("E_TEST_VALUE", path, "f32 test values must be finite numbers")
            return
        try:
            rounded = struct.unpack("<f", struct.pack("<f", value))[0]
        except (OverflowError, struct.error):
            rounded = math.inf
        if not math.isfinite(rounded):
            report.error("E_TEST_VALUE", path, "f32 test value is outside the finite f32 range")
        return
    if value_type in {"bytes", "fixed_string"}:
        size = definition.get("size")
        if not isinstance(size, int):
            return
        if value_type == "fixed_string" and isinstance(value, str):
            encoded_size = len(value.encode("utf-8"))
        elif value_type == "bytes" and isinstance(value, str):
            try:
                encoded_size = len(bytes.fromhex(value))
            except ValueError:
                report.error("E_TEST_VALUE", path, "bytes test value must be hexadecimal text")
                return
        elif isinstance(value, list) and all(
            isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 255
            for item in value
        ):
            encoded_size = len(value)
        else:
            report.error(
                "E_TEST_VALUE",
                path,
                f"{value_type} test value must be {'text' if value_type == 'fixed_string' else 'hex text'} or bytes",
            )
            return
        if encoded_size > size:
            report.error("E_TEST_VALUE", path, f"test value exceeds declared {size}-byte symbol size")
        return
    ranges = {
        "bit": (0, 1),
        "bool": (0, 1),
        "u8": (0, 0xFF),
        "s8": (-0x80, 0x7F),
        "u16": (0, 0xFFFF),
        "s16": (-0x8000, 0x7FFF),
        "u32": (0, 0xFFFFFFFF),
        "s32": (-0x80000000, 0x7FFFFFFF),
    }
    if value_type in ranges:
        minimum, maximum = ranges[value_type]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not minimum <= value <= maximum
        ):
            report.error(
                "E_TEST_VALUE", path, f"test value must be an integer in the {value_type} range"
            )


def _validate_expected_ids(
    raw: Any,
    path: str,
    achievement_ids: set[str],
    report: DiagnosticReport,
) -> set[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        report.error("E_TEST_EXPECTATION", path, "expected achievement IDs must be a string array")
        return set()
    if len(set(raw)) != len(raw):
        report.error("E_TEST_EXPECTATION", path, "expected achievement IDs must be unique")
    for identifier in raw:
        if identifier not in achievement_ids:
            report.error("E_TEST_EXPECTATION", path, f"unknown achievement id {identifier!r}")
    return set(raw)


def _validate_tests(
    document: dict[str, Any],
    symbols: dict[str, Any],
    achievement_ids: set[str],
    report: DiagnosticReport,
) -> None:
    tests = document.get("tests", [])
    if not isinstance(tests, list):
        report.error("E_TESTS", "$.tests", "tests must be an array")
        return
    names: set[str] = set()
    for index, test in enumerate(tests):
        path = f"$.tests[{index}]"
        if not isinstance(test, dict):
            report.error("E_OBJECT", path, "test must be an object")
            continue
        name = _string(test.get("name"), path + ".name", report, required=True)
        if name in names:
            report.error("E_DUPLICATE_TEST", path + ".name", f"duplicate test name {name!r}")
        if name:
            names.add(name)
        frames = test.get("frames")
        if not isinstance(frames, list) or not frames:
            report.error("E_TEST_FRAMES", path + ".frames", "test needs at least one frame")
            continue
        previous_time = -1
        for frame_index, frame in enumerate(frames):
            frame_path = f"{path}.frames[{frame_index}]"
            if not isinstance(frame, dict) or not isinstance(frame.get("values"), dict):
                report.error("E_TEST_FRAME", frame_path, "frame requires a values object")
                continue
            time_ms = frame.get("timeMs", frame_index * 100)
            if not isinstance(time_ms, int) or isinstance(time_ms, bool) or time_ms < previous_time:
                report.error("E_TEST_TIME", frame_path + ".timeMs", "frame time must be a nondecreasing integer")
            else:
                previous_time = time_ms
            for symbol, value in frame["values"].items():
                if symbol not in symbols:
                    report.error("E_UNKNOWN_SYMBOL", frame_path + ".values", f"unknown symbol {symbol!r}")
                    continue
                definition = symbols[symbol]
                if not isinstance(definition, dict):
                    continue
                resolver = definition.get("resolver")
                if isinstance(resolver, dict) and resolver.get("kind") == "derived":
                    report.error(
                        "E_TEST_VALUE",
                        frame_path + f".values.{symbol}",
                        "derived symbols are computed and cannot be assigned by a test frame",
                    )
                    continue
                _validate_test_value(
                    value, definition, frame_path + f".values.{symbol}", report
                )
        unlocked = _validate_expected_ids(
            test.get("expectUnlocked"), path + ".expectUnlocked", achievement_ids, report
        )
        locked = _validate_expected_ids(
            test.get("expectLocked", []), path + ".expectLocked", achievement_ids, report
        )
        overlap = sorted(unlocked & locked)
        if overlap:
            report.error(
                "E_TEST_EXPECTATION",
                path,
                "achievement cannot be expected both locked and unlocked: " + ", ".join(overlap),
            )
        expected_progress = test.get("expectProgress", {})
        if not isinstance(expected_progress, dict):
            report.error("E_TEST_EXPECTATION", path + ".expectProgress", "expected progress must be an object")
        else:
            for identifier, value in expected_progress.items():
                if identifier not in achievement_ids:
                    report.error(
                        "E_TEST_EXPECTATION",
                        path + ".expectProgress",
                        f"unknown achievement id {identifier!r}",
                    )
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
                    report.error(
                        "E_TEST_EXPECTATION",
                        path + f".expectProgress.{identifier}",
                        "expected progress must be an unsigned 32-bit integer",
                    )


def validate_profile(document: dict[str, Any]) -> DiagnosticReport:
    report = DiagnosticReport()
    if not isinstance(document, dict):
        report.error("E_ROOT", "$", "profile root must be an object")
        return report
    if document.get("schema") != 1:
        report.error("E_SCHEMA_VERSION", "$.schema", "only source schema version 1 is supported")
    profile = document.get("profile")
    if not isinstance(profile, dict):
        report.error("E_PROFILE", "$.profile", "profile metadata must be an object")
    else:
        for field in ("version", "license", "provenance"):
            _string(profile.get(field, ""), f"$.profile.{field}", report, required=field == "version")
        authors = profile.get("authors", [])
        if not isinstance(authors, list) or not all(isinstance(item, str) for item in authors):
            report.error("E_AUTHORS", "$.profile.authors", "authors must be a string array")
        else:
            for index, author in enumerate(authors):
                _string(author, f"$.profile.authors[{index}]", report)
    game = document.get("game")
    if not isinstance(game, dict):
        report.error("E_GAME", "$.game", "game metadata must be an object")
    else:
        if game.get("platform") != "3ds":
            report.error("E_PLATFORM", "$.game.platform", "AMUN v1 supports only native 3DS-mode profiles")
        title_id = _string(game.get("titleId"), "$.game.titleId", report, required=True)
        if title_id is not None and not TITLE_ID.fullmatch(title_id):
            report.error("E_TITLE_ID", "$.game.titleId", "titleId must contain exactly 16 hexadecimal digits")
        _string(game.get("name"), "$.game.name", report, required=True)
        _validate_builds(game, report)
    symbols = _validate_symbols(document, report)
    ordered_symbol_names(document, report)
    icons = _validate_assets(document, report)
    achievement_ids = _validate_achievements(document, symbols, icons, report)
    raw_symbols = document.get("symbols")
    _validate_tests(
        document,
        raw_symbols if isinstance(raw_symbols, dict) else {},
        achievement_ids,
        report,
    )
    return report
