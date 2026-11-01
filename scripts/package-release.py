#!/usr/bin/env python3
"""Create a deterministic, explicitly unverified AMUN release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import time
import zipfile
import zlib


ROOT = Path(__file__).resolve().parent.parent
PACK_HEADER = struct.Struct("<4sHHIIIHH16s")
PACK_SECTION = struct.Struct("<IIII")
THREE_GX_MAGIC = b"3GX$0002"
THREE_GX_HEADER_SIZE = 0x94
THREE_GX_SYMBOL_SIZE = 12
AMUN_3GX_LOADER_FLAGS = 0x3  # embedded decoders, Console, 5 MiB, loader-managed swap
AMUN_3GX_MEMORY_BYTES = 5 * 1024 * 1024
MAX_3GX_TEXT_FIELD_BYTES = 4096
MAX_PACK_BYTES = 2 * 1024 * 1024
SUPPORTED_PACK_MAJOR = 1
SUPPORTED_PACK_MINOR = 1  # pack 1.1 adds pointer-chain resolvers; keep equal to compiler.pack.PACK_MINOR
DEFAULT_EPOCH = 946684800  # 2000-01-01T00:00:00Z
CTRPF_LICENSE_SHA256 = "0979856970773de8c1429acddc0968297fd91426f4980b170a45ec6a37c123d0"
LIBCTRU_LICENSE_SHA256 = "093b82e887bd249d69dd9148aa7d582a599d72b4ad9122e0f3115023b82d3a26"


class ReleaseError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_version(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}", value):
        raise argparse.ArgumentTypeError("version must be 1-64 filename-safe characters")
    return value


def _direct_output_child(output: Path, name: str) -> Path:
    """Resolve one generated target and require it to remain a direct output child."""
    candidate = (output / name).resolve()
    if candidate.parent != output or candidate.name != name:
        raise ReleaseError(f"release target escapes the output directory: {candidate}")
    return candidate


def _source_epoch(raw: int | None) -> int:
    if raw is None:
        raw = int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH))
    if raw < 315532800:  # ZIP timestamps cannot precede 1980.
        raise ReleaseError("SOURCE_DATE_EPOCH must be 1980-01-01 or later")
    if raw > 4354819199:  # ZIP DOS timestamp ends at 2107-12-31 23:59:59.
        raise ReleaseError("SOURCE_DATE_EPOCH must not exceed 2107-12-31")
    return raw


def _copy_file(source: Path, destination: Path, epoch: int) -> None:
    if source.is_symlink():
        raise ReleaseError(f"release inputs may not be symlinks: {source}")
    if not source.is_file():
        raise ReleaseError(f"required release input is absent: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    mode = 0o755 if source.suffix in {".sh", ".py"} and source.parent.name == "scripts" else 0o644
    os.chmod(destination, mode)
    os.utime(destination, (epoch, epoch))


def _copy_verified_file(source: Path, destination: Path, expected_sha256: str, epoch: int) -> None:
    """Copy one inspected input and fail if it changed between inspection and staging."""
    _copy_file(source, destination, epoch)
    actual = _sha256(destination)
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReleaseError(f"release input changed while it was being staged: {source}")


def _copy_tree(source: Path, destination: Path, epoch: int, *, include_tests: bool = False) -> None:
    if source.is_symlink():
        raise ReleaseError(f"release input directories may not be symlinks: {source}")
    if not source.is_dir():
        raise ReleaseError(f"required release directory is absent: {source}")
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(source)
        if any(part in {"__pycache__", ".git", "build"} for part in relative.parts):
            continue
        if not include_tests and any(part in {"tests", "test"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise ReleaseError(f"release inputs may not contain symlinks: {path}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            _copy_file(path, destination / relative, epoch)


def _write_text(path: Path, text: str, epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n").rstrip() + "\n", encoding="utf-8", newline="\n")
    os.chmod(path, 0o644)
    os.utime(path, (epoch, epoch))


def _verify_3gx(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ReleaseError(f"3GX input is absent: {path}")
    file_size = path.stat().st_size
    if file_size < THREE_GX_HEADER_SIZE:
        raise ReleaseError(f"3GX header is truncated: {path}")
    with path.open("rb") as stream:
        header = stream.read(THREE_GX_HEADER_SIZE)
    magic = header[: len(THREE_GX_MAGIC)]
    if magic != THREE_GX_MAGIC:
        raise ReleaseError(
            f"{path} is not a current 3GX file: expected first bytes {THREE_GX_MAGIC!r}"
        )
    if struct.unpack_from("<I", header, 0x0C)[0] != 0:
        raise ReleaseError(f"3GX reserved header word is nonzero: {path}")

    flags = struct.unpack_from("<I", header, 0x30)[0]
    if flags & ~0x3FF or ((flags >> 2) & 0x3) == 0x3 or ((flags >> 4) & 0x3) == 0x3:
        raise ReleaseError(f"3GX contains reserved loader flags: {path}")
    if flags != AMUN_3GX_LOADER_FLAGS:
        raise ReleaseError(
            "3GX loader policy is not the stable AMUN Console/5MiB/"
            f"loader-managed/non-private policy: {path}"
        )

    def require_span(label: str, offset: int, size: int, *, floor: int = THREE_GX_HEADER_SIZE) -> None:
        if offset < floor or size < 0 or offset > file_size or size > file_size - offset:
            raise ReleaseError(f"3GX {label} range is out of bounds: {path}")

    text_fields: list[tuple[str, int, int]] = []
    for index, label in enumerate(("author", "title", "summary", "description")):
        length, offset = struct.unpack_from("<II", header, 0x10 + index * 8)
        if length == 0:
            if offset != 0:
                raise ReleaseError(f"3GX empty {label} has a nonzero offset: {path}")
            continue
        if length > MAX_3GX_TEXT_FIELD_BYTES:
            raise ReleaseError(f"3GX {label} metadata is unreasonably large: {path}")
        require_span(label, offset, length)
        text_fields.append((label, offset, length))

    (
        code_offset,
        rodata_offset,
        data_offset,
        code_size,
        rodata_size,
        data_size,
        bss_size,
        exe_decoder_offset,
        swap_encoder_offset,
        swap_decoder_offset,
    ) = struct.unpack_from("<10I", header, 0x58)
    if code_size == 0 or code_offset % 16 != 0:
        raise ReleaseError(f"3GX code section is empty or unaligned: {path}")
    require_span("code", code_offset, code_size)
    require_span("rodata", rodata_offset, rodata_size)
    require_span("data", data_offset, data_size)
    if rodata_offset != code_offset + code_size or data_offset != rodata_offset + rodata_size:
        raise ReleaseError(f"3GX executable sections are not contiguous: {path}")
    loaded_bytes = code_size + rodata_size + data_size + bss_size
    if loaded_bytes > AMUN_3GX_MEMORY_BYTES:
        raise ReleaseError(f"3GX loaded sections exceed the AMUN 5 MiB region: {path}")
    for label, offset in (
        ("executable decoder", exe_decoder_offset),
        ("swap encoder", swap_encoder_offset),
        ("swap decoder", swap_decoder_offset),
    ):
        if offset != 0 and not THREE_GX_HEADER_SIZE <= offset < code_offset:
            raise ReleaseError(f"3GX {label} offset is out of bounds: {path}")

    target_count, target_offset = struct.unpack_from("<II", header, 0x80)
    if target_count != 0 or target_offset != 0:
        raise ReleaseError(f"3GX is not the target-free AMUN fallback plugin: {path}")

    symbol_count, symbol_offset, name_table_offset = struct.unpack_from("<III", header, 0x88)
    if symbol_count == 0:
        if symbol_offset != 0 or name_table_offset != 0:
            raise ReleaseError(f"3GX empty symbol table has nonzero offsets: {path}")
    else:
        require_span("symbol table", symbol_offset, symbol_count * THREE_GX_SYMBOL_SIZE)
        symbol_end = symbol_offset + symbol_count * THREE_GX_SYMBOL_SIZE
        if name_table_offset < symbol_end or name_table_offset >= file_size:
            raise ReleaseError(f"3GX symbol-name table offset is out of bounds: {path}")

    with path.open("rb") as stream:
        for label, offset, length in text_fields:
            stream.seek(offset)
            value = stream.read(length)
            if len(value) != length or value[-1:] != b"\0":
                raise ReleaseError(f"3GX {label} metadata is not NUL terminated: {path}")

    return {"bytes": file_size, "sha256": _sha256(path)}


def _verify_elf(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ReleaseError(f"ELF input is absent: {path}")
    with path.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise ReleaseError(f"debug-symbol input is not an ELF file: {path}")
    return {"bytes": path.stat().st_size, "sha256": _sha256(path)}


def _inspect_pack(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ReleaseError(f"pack input is absent: {path}")
    if path.stat().st_size > MAX_PACK_BYTES:
        raise ReleaseError(
            f"pack exceeds the {MAX_PACK_BYTES}-byte release limit: {path}"
        )
    data = path.read_bytes()
    if len(data) < PACK_HEADER.size:
        raise ReleaseError(f"pack has a truncated header: {path}")
    magic, major, minor, total_size, checksum, _flags, section_count, header_size, profile_hash = PACK_HEADER.unpack_from(data)
    if magic != b"AMUN" or major != SUPPORTED_PACK_MAJOR or minor > SUPPORTED_PACK_MINOR:
        raise ReleaseError(f"pack has unsupported magic/version: {path}")
    if total_size != len(data):
        raise ReleaseError(f"pack declared size does not match file size: {path}")
    if not 1 <= section_count <= 16 or header_size != PACK_HEADER.size + section_count * PACK_SECTION.size:
        raise ReleaseError(f"pack has an invalid section directory: {path}")
    if zlib.crc32(data[header_size:]) & 0xFFFFFFFF != checksum:
        raise ReleaseError(f"pack payload CRC-32 mismatch: {path}")
    manifest: tuple[int, int] | None = None
    ranges: list[tuple[int, int]] = []
    for index in range(section_count):
        section_type, offset, size, _count = PACK_SECTION.unpack_from(
            data, PACK_HEADER.size + index * PACK_SECTION.size
        )
        if offset < header_size or offset + size > len(data):
            raise ReleaseError(f"pack section {section_type} is out of bounds: {path}")
        ranges.append((offset, offset + size))
        if section_type == 1:
            if manifest is not None:
                raise ReleaseError(f"pack has duplicate manifest sections: {path}")
            manifest = (offset, size)
    ranges.sort()
    if any(right_start < left_end for (_left_start, left_end), (right_start, _right_end) in zip(ranges, ranges[1:])):
        raise ReleaseError(f"pack sections overlap: {path}")
    if manifest is None or manifest[1] != 28:
        raise ReleaseError(f"pack manifest is absent or malformed: {path}")
    title_id = struct.unpack_from("<Q", data, manifest[0])[0]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from compiler.pack import PackError, inspect_pack

        authoritative = inspect_pack(data)
    except (ImportError, PackError, ValueError) as error:
        raise ReleaseError(f"authoritative pack inspection failed for {path}: {error}") from error
    authoritative_title = str(authoritative["manifest"]["titleId"])
    if authoritative_title != f"{title_id:016X}":
        raise ReleaseError(f"pack parsers disagree about Title ID: {path}")
    return {
        "titleId": authoritative_title,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "profileHash": profile_hash.hex(),
    }


def _parse_pack_argument(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise ReleaseError("--pack must use FULL_TITLE_ID=path")
    raw_title, raw_path = raw.split("=", 1)
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", raw_title):
        raise ReleaseError(f"invalid full 16-digit Title ID in --pack: {raw_title!r}")
    return raw_title.upper(), Path(raw_path).expanduser().resolve()


def _manifest(stage: Path, epoch: int) -> None:
    entries: list[str] = []
    for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name != "SHA256SUMS":
            relative = path.relative_to(stage).as_posix()
            entries.append(f"{_sha256(path)}  {relative}")
    _write_text(stage / "SHA256SUMS", "\n".join(entries), epoch)


def _normalize_tree(stage: Path, epoch: int) -> None:
    for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix(), reverse=True):
        os.utime(path, (epoch, epoch))
    os.utime(stage, (epoch, epoch))


def _write_zip(stage: Path, destination: Path, epoch: int) -> None:
    timestamp = time.gmtime(epoch)[:6]
    temporary = _direct_output_child(destination.parent, destination.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix()):
                relative = (Path(stage.name) / path.relative_to(stage)).as_posix()
                if path.is_dir():
                    info = zipfile.ZipInfo(relative.rstrip("/") + "/", timestamp)
                    info.create_system = 3
                    info.external_attr = (0o755 << 16) | 0x10
                    archive.writestr(info, b"")
                    continue
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo(relative, timestamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                mode = path.stat().st_mode & 0o777
                info.external_attr = mode << 16
                archive.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary, destination)
        os.utime(destination, (epoch, epoch))
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _stage_python_product(stage: Path, name: str, packages: tuple[str, ...], epoch: int) -> None:
    destination = stage / name
    _copy_file(ROOT / "amun.py", destination / "amun.py", epoch)
    for package in packages:
        _copy_tree(ROOT / package, destination / package, epoch)
    _copy_tree(ROOT / "profiles" / "schema", destination / "profiles" / "schema", epoch)
    _copy_tree(ROOT / "formats", destination / "formats", epoch)
    _copy_file(ROOT / "LICENSE", destination / "LICENSE", epoch)


def build_release(arguments: argparse.Namespace) -> tuple[Path, Path | None]:
    epoch = _source_epoch(arguments.source_date_epoch)
    output = arguments.output.expanduser().resolve()
    try:
        version = _safe_version(arguments.version)
    except argparse.ArgumentTypeError as error:
        raise ReleaseError(str(error)) from error
    stage_name = f"AMUN-3DS-v{version}"
    stage = _direct_output_child(output, stage_name)
    archive = _direct_output_child(output, f"{stage_name}.zip") if arguments.zip else None
    if stage.exists() and not arguments.replace:
        raise ReleaseError(f"release stage already exists (pass --replace): {stage}")
    if archive is not None and archive.exists() and not arguments.replace:
        raise ReleaseError(f"release archive already exists (pass --replace): {archive}")
    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{stage_name}-", dir=output))
    plugin_metadata: dict[str, object] = {"included": False, "hardwareVerified": False}
    pack_metadata: list[dict[str, object]] = []
    try:
        for source_name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            _copy_file(ROOT / source_name, temporary / source_name, epoch)
        _copy_tree(ROOT / "assets", temporary / "assets", epoch)
        _copy_tree(ROOT / "LICENSES", temporary / "LICENSES", epoch)
        _copy_tree(ROOT / "docs", temporary / "docs", epoch)
        _copy_tree(ROOT / "formats", temporary / "formats", epoch)

        _stage_python_product(temporary, "amun-cli", ("cli", "compiler"), epoch)
        _stage_python_product(temporary, "amun-studio", ("studio", "cli", "compiler"), epoch)
        _copy_tree(ROOT / "hub", temporary / "amun-hub" / "hub", epoch)
        _copy_file(ROOT / "LICENSE", temporary / "amun-hub" / "LICENSE", epoch)

        _copy_tree(ROOT / "profiles" / "examples", temporary / "example-profiles" / "examples", epoch)
        _copy_tree(ROOT / "profiles" / "synthetic", temporary / "example-profiles" / "synthetic", epoch)
        _copy_tree(
            ROOT / "profiles" / "hardware-self-test",
            temporary / "example-profiles" / "hardware-self-test",
            epoch,
        )
        _copy_tree(ROOT / "profiles" / "schema", temporary / "example-profiles" / "schema", epoch)
        # Keep the repository-relative documentation targets valid in the release while
        # retaining the friendlier example-profiles collection for users browsing it.
        _copy_tree(
            ROOT / "profiles" / "hardware-self-test",
            temporary / "profiles" / "hardware-self-test",
            epoch,
        )
        _copy_tree(ROOT / "profiles" / "schema", temporary / "profiles" / "schema", epoch)

        patch_destination = temporary / "dependency-patches"
        _copy_tree(ROOT / "cmake" / "3ds" / "patches", patch_destination / "patches", epoch)
        for name in (
            "Dependencies.cmake",
            "fetch_pinned_dependencies.cmake",
            "build_pinned_dependencies.cmake",
            "verify_patched_ctrpf.cmake",
        ):
            _copy_file(ROOT / "cmake" / "3ds" / name, patch_destination / name, epoch)

        sd_root = temporary / "sd-root"
        for relative in (
            "luma/plugins",
            "amun/config",
            "amun/ledger",
            "amun/logs",
            "amun/packs",
        ):
            (sd_root / relative).mkdir(parents=True, exist_ok=True)
        _copy_file(
            ROOT / "3ds" / "config" / "self-test.flag.example",
            sd_root / "amun" / "config" / "self-test.flag.example",
            epoch,
        )

        if arguments.three_gx is not None:
            source_3gx = arguments.three_gx.expanduser().resolve()
            plugin_metadata.update(_verify_3gx(source_3gx))
            plugin_metadata["included"] = True
            staged_3gx = temporary / "AMUN.3gx"
            _copy_verified_file(source_3gx, staged_3gx, str(plugin_metadata["sha256"]), epoch)
            _copy_file(staged_3gx, sd_root / "luma" / "plugins" / "default.3gx", epoch)
            if arguments.elf is not None:
                source_elf = arguments.elf.expanduser().resolve()
                plugin_metadata["elf"] = _verify_elf(source_elf)
                _copy_verified_file(
                    source_elf,
                    temporary / "debug" / "AMUN.elf",
                    str(plugin_metadata["elf"]["sha256"]),
                    epoch,
                )
            if arguments.map_file is not None:
                source_map = arguments.map_file.expanduser().resolve()
                if not source_map.is_file() or source_map.stat().st_size == 0:
                    raise ReleaseError(f"link-map input is absent or empty: {source_map}")
                plugin_metadata["map"] = {
                    "bytes": source_map.stat().st_size,
                    "sha256": _sha256(source_map),
                }
                _copy_verified_file(
                    source_map,
                    temporary / "debug" / "AMUN.map",
                    str(plugin_metadata["map"]["sha256"]),
                    epoch,
                )
            license_source = arguments.ctrpf_license.expanduser().resolve()
            expected_license = ROOT / "LICENSES" / "CTRPluginFramework-LICENSE.txt"
            if (
                _sha256(license_source) != CTRPF_LICENSE_SHA256
                or _sha256(expected_license) != CTRPF_LICENSE_SHA256
            ):
                raise ReleaseError("CTRPluginFramework license does not match the reviewed pinned license")
            _copy_file(license_source, temporary / "LICENSES" / "CTRPluginFramework-LICENSE.txt", epoch)
            libctru_license = ROOT / "LICENSES" / "libctru-LICENSE.txt"
            if _sha256(libctru_license) != LIBCTRU_LICENSE_SHA256:
                raise ReleaseError("libctru license does not match the reviewed 2.7.0 notice")
        elif arguments.require_3gx:
            raise ReleaseError("--require-3gx was set but no --3gx input was supplied")
        else:
            if arguments.elf is not None or arguments.map_file is not None:
                raise ReleaseError("--elf/--map-file require a --3gx input")
            _write_text(
                temporary / "NO-3GX.txt",
                "This is a host-tools bundle. It does not contain AMUN.3gx and is not an installable console release.\nSee docs/3ds-toolchain.md to produce and verify a plugin.",
                epoch,
            )

        for raw_pack in arguments.pack:
            requested_title, source_pack = _parse_pack_argument(raw_pack)
            inspected = _inspect_pack(source_pack)
            if inspected["titleId"] != requested_title:
                raise ReleaseError(
                    f"pack Title ID {inspected['titleId']} does not match requested path {requested_title}"
                )
            destination = sd_root / "amun" / "packs" / requested_title / "game.amunpack"
            staged_pack = temporary / "example-profiles" / "compiled" / f"{requested_title}-game.amunpack"
            _copy_verified_file(
                source_pack,
                staged_pack,
                str(inspected["sha256"]),
                epoch,
            )
            _copy_file(staged_pack, destination, epoch)
            pack_metadata.append(inspected)

        release_status = "plugin-present-not-hardware-verified" if plugin_metadata["included"] else "host-tools-only"
        metadata = {
            "format": 1,
            "hardwareVerified": False,
            "name": "AMUN 3DS",
            "version": arguments.version,
            "sourceDateEpoch": epoch,
            "status": release_status,
            "plugin": plugin_metadata,
            "packs": pack_metadata,
            "sdRoot": "sd-root",
        }
        _write_text(
            temporary / "release.json",
            json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False),
            epoch,
        )
        _manifest(temporary, epoch)
        _normalize_tree(temporary, epoch)

        if stage.exists():
            if _direct_output_child(output, stage_name) != stage:
                raise ReleaseError("release stage target changed during packaging")
            shutil.rmtree(stage)
        os.replace(temporary, stage)
        if archive is not None:
            if archive.exists():
                if _direct_output_child(output, f"{stage_name}.zip") != archive:
                    raise ReleaseError("release archive target changed during packaging")
                archive.unlink()
            _write_zip(stage, archive, epoch)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return stage, archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="stage deterministic AMUN host tools and, when supplied, a verified-magic 3GX"
    )
    parser.add_argument("--version", type=_safe_version, default="0.1.0")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release")
    parser.add_argument("--3gx", dest="three_gx", type=Path)
    parser.add_argument("--elf", type=Path, help="optional matching debug-symbol ELF")
    parser.add_argument("--map-file", type=Path, help="optional matching linker map")
    parser.add_argument("--require-3gx", action="store_true")
    parser.add_argument(
        "--ctrpf-license",
        type=Path,
        default=ROOT / "LICENSES" / "CTRPluginFramework-LICENSE.txt",
    )
    parser.add_argument(
        "--pack",
        action="append",
        default=[],
        metavar="FULL_TITLE_ID=PATH",
        help="validate and stage one exact-title pack (repeatable)",
    )
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--zip", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--replace", action="store_true")
    return parser


def main() -> int:
    try:
        stage, archive = build_release(build_parser().parse_args())
    except (ReleaseError, OSError, ValueError, struct.error) as error:
        print(f"release error: {error}", file=sys.stderr)
        return 1
    print(f"staged {stage}")
    if archive is not None:
        print(f"archive {archive} sha256={_sha256(archive)}")
    print("hardware verification: NOT PERFORMED BY PACKAGING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
