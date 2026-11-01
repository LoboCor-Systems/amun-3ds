"""Unified ``amun`` command implemented with Python's standard library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from compiler import __version__
from compiler.diagnostics import CompilationFailed
from compiler.dump import DumpError, FORMATS, diff_dumps, search_dump
from compiler.importer import ImportError as RaImportError, import_ra_file, write_imported_profile
from compiler.metal_tiers import MetalTier, format_tier_counts, tier_counts
from compiler.pack import PackError, compile_profile, inspect_pack, write_pack
from compiler.profile import ProfileLoadError, load_profile
from compiler.replay import ReplayError, replay_trace
from compiler.simulator import run_profile_tests
from compiler.trace import TraceError, inspect_trace


def _integer(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected integer or 0x-prefixed value: {text}") from error


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _diagnostics(error: CompilationFailed, json_output: bool) -> int:
    if json_output:
        _json(error.report.to_dict())
    else:
        print(error.report.format(), file=sys.stderr)
    return 1


def _profile_validate(arguments: argparse.Namespace) -> int:
    loaded = load_profile(arguments.project)
    try:
        compiled = compile_profile(loaded)
    except CompilationFailed as error:
        return _diagnostics(error, arguments.json)
    result = {
        "ok": True,
        "profile": str(loaded.profile_path),
        "symbols": len(compiled.symbol_names),
        "achievements": len(compiled.achievement_ids),
        "assets": len(compiled.asset_names),
        "compiledBytes": len(compiled.data),
        "profileHash": compiled.profile_hash.hex(),
    }
    if arguments.json:
        _json(result)
    else:
        print(
            f"valid: {loaded.profile_path}\n"
            f"  {result['symbols']} symbols, {result['achievements']} achievements, "
            f"{result['assets']} assets; compiled size {result['compiledBytes']} bytes\n"
            f"  canonical source hash: {result['profileHash']}"
        )
    return 0


def _default_pack_path(loaded) -> Path:
    return loaded.project_root / "build" / f"{loaded.profile_path.stem}.amunpack"


def _profile_build(arguments: argparse.Namespace) -> int:
    loaded = load_profile(arguments.project)
    try:
        compiled = compile_profile(loaded)
    except CompilationFailed as error:
        return _diagnostics(error, arguments.json)
    destination = Path(arguments.output).expanduser().resolve() if arguments.output else _default_pack_path(loaded)
    written = write_pack(compiled, destination)
    result = {
        "ok": True,
        "profile": str(loaded.profile_path),
        "output": str(written),
        "size": len(compiled.data),
        "sha256": compiled.sha256,
        "profileHash": compiled.profile_hash.hex(),
    }
    if arguments.json:
        _json(result)
    else:
        print(f"built {written} ({len(compiled.data)} bytes)\nsha256 {compiled.sha256}")
    return 0


def _profile_test(arguments: argparse.Namespace) -> int:
    loaded = load_profile(arguments.project)
    try:
        results = run_profile_tests(loaded, scenario_name=arguments.scenario)
    except CompilationFailed as error:
        return _diagnostics(error, arguments.json)
    output = {
        "ok": all(result.passed for result in results),
        "profile": str(loaded.profile_path),
        "scenarioCount": len(results),
        "scenarios": [
            {
                "name": result.name,
                "passed": result.passed,
                "failures": list(result.failures),
                "unlocked": list(result.unlocked),
                "progress": result.progress,
            }
            for result in results
        ],
    }
    if arguments.json:
        _json(output)
    else:
        if not results:
            print("warning: profile has no test scenarios", file=sys.stderr)
        for result in results:
            print(f"{'PASS' if result.passed else 'FAIL'} {result.name}")
            for failure in result.failures:
                print(f"  {failure}")
        print(f"{sum(result.passed for result in results)}/{len(results)} scenario(s) passed")
    return 0 if output["ok"] else 1


def _pack_inspect(arguments: argparse.Namespace) -> int:
    result = inspect_pack(arguments.pack)
    if arguments.json:
        _json(result)
    else:
        manifest = result["manifest"]
        print(
            f"AMUN pack {result['version']} - {result['totalSize']} bytes\n"
            f"{manifest['gameName']} ({manifest['titleId']}) profile {manifest['profileVersion']}\n"
            f"{len(result['builds'])} build(s), {len(result['symbols'])} symbol(s), "
            f"{len(result['achievements'])} achievement(s), {len(result['assets'])} asset(s)\n"
            f"CRC32 {result['crc32']}  profile hash {result['profileHash']}"
        )
        counts = tier_counts(achievement["points"] for achievement in result["achievements"])
        ranked = format_tier_counts(counts)
        unranked = counts[MetalTier.NONE]
        print(f"Metals: {ranked or 'none'}" + (f" ({unranked} unranked)" if unranked else ""))
        if arguments.disassemble:
            for achievement in result["achievements"]:
                print(f"\n[{achievement['id']}] stack={achievement['maxStack']} "
                      f"slots={achievement['stateSlots']} budget={achievement['instructionBudget']}")
                for line in achievement["disassembly"]:
                    print("  " + line)
    return 0


def _trace_inspect(arguments: argparse.Namespace) -> int:
    result = inspect_trace(arguments.trace, include_frames=arguments.frames)
    if arguments.json:
        _json(result)
    else:
        print(
            f"AMTR {result['version']} - title {result['titleId']} build {result['buildId']}\n"
            f"{result['frameCount']} frame(s), {result['readCount']} read(s), "
            f"{result['readBytes']} byte(s), {result['uniqueReadAddresses']} unique address(es)\n"
            f"profile hash {result['profileHash']}"
        )
        if arguments.frames:
            for frame in result.get("frames", []):
                print(f"  frame {frame['index']} @{frame['monotonicMs']}ms: {len(frame['reads'])} read(s)")
    return 0


def _trace_replay(arguments: argparse.Namespace) -> int:
    return replay_trace(
        arguments.trace,
        arguments.pack,
        ledger=arguments.ledger,
        simulator=arguments.simulator,
    )


def _dump_search(arguments: argparse.Namespace) -> int:
    result = search_dump(
        arguments.dump,
        value_type=arguments.type,
        value=arguments.value,
        base_address=arguments.base,
        stride=arguments.stride,
        limit=arguments.limit,
    )
    if arguments.json:
        _json(result)
    else:
        for match in result["matches"]:
            print(f"{match['address']}  {match['value']}")
        suffix = " (output truncated)" if result["truncated"] else ""
        print(f"{result['matchCount']} match(es){suffix}")
    return 0


def _dump_diff(arguments: argparse.Namespace) -> int:
    result = diff_dumps(
        arguments.before,
        arguments.after,
        value_type=arguments.type,
        mode=arguments.mode,
        base_address=arguments.base,
        stride=arguments.stride,
        by=arguments.by,
        limit=arguments.limit,
    )
    if arguments.json:
        _json(result)
    else:
        if result["sizeMismatch"]:
            print("warning: dump sizes differ; only their common prefix was compared", file=sys.stderr)
        for match in result["matches"]:
            print(f"{match['address']}  {match['before']} -> {match['after']}")
        suffix = " (output truncated)" if result["truncated"] else ""
        print(f"{result['matchCount']} match(es){suffix}")
    return 0


def _sim_run(arguments: argparse.Namespace) -> int:
    loaded = load_profile(arguments.project)
    try:
        results = run_profile_tests(loaded, scenario_name=arguments.scenario)
    except CompilationFailed as error:
        return _diagnostics(error, arguments.json)
    output = {
        "ok": all(result.passed for result in results),
        "scenarios": [
            {
                "name": result.name,
                "passed": result.passed,
                "failures": list(result.failures),
                "unlocked": list(result.unlocked),
                "progress": result.progress,
                "frames": list(result.frames),
            }
            for result in results
        ],
    }
    if arguments.json:
        _json(output)
    else:
        for result in results:
            print(f"scenario {result.name}: {'PASS' if result.passed else 'FAIL'}")
            for frame in result.frames:
                if frame["unlocked"] or frame["progress"]:
                    print(
                        f"  frame {frame['index']} @{frame['timeMs']}ms "
                        f"unlocked={frame['unlocked']} progress={frame['progress']}"
                    )
            for failure in result.failures:
                print("  " + failure)
    return 0 if output["ok"] else 1


def _import_ra(arguments: argparse.Namespace) -> int:
    document, warnings = import_ra_file(arguments.input)
    source = Path(arguments.input).expanduser().resolve()
    destination = (
        Path(arguments.output).expanduser().resolve()
        if arguments.output
        else source.with_name(source.stem + ".amun-profile.json")
    )
    if destination.exists() and not arguments.force:
        raise RaImportError(f"output already exists: {destination}; pass --force to replace it")
    written = write_imported_profile(document, destination)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if arguments.json:
        _json({"ok": True, "output": str(written), "warnings": warnings})
    else:
        print(f"wrote imported draft {written}\n{len(warnings)} warning(s); validate and test before use")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amun", description="AMUN 3DS profile and research tools")
    parser.add_argument("--version", action="version", version=f"AMUN host tools {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="validate, compile, and test source profiles")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    validate = profile_commands.add_parser("validate", help="validate and dry-compile a profile")
    validate.add_argument("project")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=_profile_validate)
    build = profile_commands.add_parser("build", help="compile a deterministic .amunpack")
    build.add_argument("project")
    build.add_argument("-o", "--output")
    build.add_argument("--json", action="store_true")
    build.set_defaults(handler=_profile_build)
    test = profile_commands.add_parser("test", help="run embedded deterministic scenarios")
    test.add_argument("project")
    test.add_argument("--scenario")
    test.add_argument("--json", action="store_true")
    test.set_defaults(handler=_profile_test)

    pack = commands.add_parser("pack", help="inspect compiled packs")
    pack_commands = pack.add_subparsers(dest="pack_command", required=True)
    pack_inspect = pack_commands.add_parser("inspect", help="validate and describe an .amunpack")
    pack_inspect.add_argument("pack")
    pack_inspect.add_argument("--json", action="store_true")
    pack_inspect.add_argument("--disassemble", action="store_true")
    pack_inspect.set_defaults(handler=_pack_inspect)

    trace = commands.add_parser("trace", help="inspect replay traces")
    trace_commands = trace.add_subparsers(dest="trace_command", required=True)
    trace_inspect = trace_commands.add_parser("inspect", help="validate and describe an .amuntrace")
    trace_inspect.add_argument("trace")
    trace_inspect.add_argument("--json", action="store_true")
    trace_inspect.add_argument("--frames", action="store_true")
    trace_inspect.set_defaults(handler=_trace_inspect)
    trace_replay = trace_commands.add_parser(
        "replay", help="replay a trace through the authoritative C++ runtime"
    )
    trace_replay.add_argument("trace", help="local .amuntrace input")
    trace_replay.add_argument("pack", help="matching local .amunpack input")
    trace_replay.add_argument("--ledger", help="optional persistent replay ledger path")
    trace_replay.add_argument(
        "--simulator",
        help="amun-sim executable (otherwise AMUN_SIMULATOR, PATH, and CMake build paths are checked)",
    )
    trace_replay.set_defaults(handler=_trace_replay)

    dump = commands.add_parser("dump", help="search and compare local memory dumps")
    dump_commands = dump.add_subparsers(dest="dump_command", required=True)
    search = dump_commands.add_parser("search", help="search a raw dump for an exact value")
    search.add_argument("dump")
    search.add_argument("--type", choices=tuple(FORMATS), required=True)
    search.add_argument("--value", required=True)
    search.add_argument("--base", type=_integer, default=0)
    search.add_argument("--stride", type=_integer, default=1)
    search.add_argument("--limit", type=int, default=1000)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=_dump_search)
    diff = dump_commands.add_parser("diff", help="compare typed values in two raw dumps")
    diff.add_argument("before")
    diff.add_argument("after")
    diff.add_argument("--type", choices=tuple(FORMATS), required=True)
    diff.add_argument("--mode", choices=("changed", "unchanged", "increased", "decreased", "by"), default="changed")
    diff.add_argument("--by")
    diff.add_argument("--base", type=_integer, default=0)
    diff.add_argument("--stride", type=_integer, default=1)
    diff.add_argument("--limit", type=int, default=1000)
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(handler=_dump_diff)

    sim = commands.add_parser("sim", help="run host profile scenarios")
    sim_commands = sim.add_subparsers(dest="sim_command", required=True)
    sim_run = sim_commands.add_parser("run", help="run one or all embedded scenarios")
    sim_run.add_argument("project")
    sim_run.add_argument("--scenario")
    sim_run.add_argument("--json", action="store_true")
    sim_run.set_defaults(handler=_sim_run)

    importer = commands.add_parser("import-ra", help="conservatively import a local RA-style JSON draft")
    importer.add_argument("input")
    importer.add_argument("-o", "--output")
    importer.add_argument("--force", action="store_true")
    importer.add_argument("--json", action="store_true")
    importer.set_defaults(handler=_import_ra)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except (
        ProfileLoadError,
        PackError,
        TraceError,
        DumpError,
        RaImportError,
        ReplayError,
        ValueError,
        OSError,
    ) as error:
        if getattr(arguments, "json", False):
            _json({"ok": False, "error": str(error)})
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
