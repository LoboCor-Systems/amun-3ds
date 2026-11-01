"""Filesystem-backed, offline AMUN profile-pack library.

Scanning and opening are deliberately read-only.  The only methods that write
are :meth:`ProfileLibrary.import_pack` and :meth:`ProfileLibrary.export_pack`,
and both require an explicit destination and refuse implicit overwrites.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import tempfile
from typing import Iterable
import zlib


PACK_EXTENSION = ".amunpack"
MAX_PACK_BYTES = 2 * 1024 * 1024

_HEADER = struct.Struct("<4sHHIIIHH16s")
_SECTION = struct.Struct("<IIII")
_MANIFEST = struct.Struct("<QIIIII")
_BUILD = struct.Struct("<IIIIIB3x")
_SYMBOL_SIZE = 32
_ACHIEVEMENT_SIZE = 56
_ASSET_SIZE = 24
_REQUIRED_SECTIONS = frozenset(range(1, 8))


class LibraryError(ValueError):
    """Raised when a library path or pack cannot be handled safely."""


class LibraryConflict(LibraryError):
    """Raised when a copy would replace an existing file without consent."""


class InvalidPack(LibraryError):
    """Raised when a file is not a structurally valid AMUN pack."""


@dataclass(frozen=True)
class PackBuild:
    identifier: str
    region: str
    application_version: str
    update_version: str
    fingerprint: str
    compatible: bool

    @property
    def label(self) -> str:
        version = self.application_version or self.update_version
        detail = " ".join(part for part in (self.region, version) if part)
        return detail or self.identifier


@dataclass(frozen=True)
class PackSummary:
    title_id: str
    game_name: str
    profile_version: str
    license: str
    provenance: str
    builds: tuple[PackBuild, ...]
    symbol_count: int
    achievement_count: int
    asset_count: int
    format_version: str
    source_hash: str


@dataclass(frozen=True)
class LibraryEntry:
    relative_path: Path
    path: Path
    size: int
    modified_ns: int
    sha256: str
    summary: PackSummary | None
    error: str | None = None

    @property
    def key(self) -> str:
        return self.relative_path.as_posix()

    @property
    def valid(self) -> bool:
        return self.summary is not None and self.error is None


@dataclass(frozen=True)
class _SectionRecord:
    offset: int
    size: int
    count: int


def _string_reader(data: bytes):
    if not data or data[0] != 0:
        raise InvalidPack("string section must begin with an empty string")

    def read(offset: int) -> str:
        if not 0 <= offset < len(data):
            raise InvalidPack(f"string offset {offset} is outside the string section")
        end = data.find(b"\0", offset)
        if end < 0:
            raise InvalidPack(f"string at offset {offset} is not NUL-terminated")
        try:
            return data[offset:end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidPack(f"string at offset {offset} is not valid UTF-8") from error

    return read


def inspect_pack_bytes(data: bytes) -> PackSummary:
    """Validate the bounded pack envelope and return display-safe metadata."""

    if len(data) > MAX_PACK_BYTES:
        raise InvalidPack(f"pack exceeds the {MAX_PACK_BYTES}-byte Studio limit")
    if len(data) < _HEADER.size:
        raise InvalidPack("pack header is truncated")
    (
        magic,
        major,
        minor,
        total_size,
        expected_crc,
        _flags,
        section_count,
        header_size,
        source_hash,
    ) = _HEADER.unpack_from(data)
    if magic != b"AMUN":
        raise InvalidPack("file does not have AMUN pack magic")
    if major != 1 or minor > 0:
        raise InvalidPack(f"unsupported AMUN pack version {major}.{minor}")
    if total_size != len(data):
        raise InvalidPack("declared pack size differs from file size")
    if not 1 <= section_count <= 16:
        raise InvalidPack("section count is outside the supported range")
    if header_size != _HEADER.size + section_count * _SECTION.size:
        raise InvalidPack("section directory size is inconsistent")
    if header_size > len(data):
        raise InvalidPack("section directory exceeds the file")
    if zlib.crc32(data[header_size:]) & 0xFFFFFFFF != expected_crc:
        raise InvalidPack("pack payload CRC-32 does not match")

    sections: dict[int, _SectionRecord] = {}
    occupied: list[tuple[int, int]] = []
    for index in range(section_count):
        section_type, offset, size, count = _SECTION.unpack_from(
            data, _HEADER.size + index * _SECTION.size
        )
        if section_type in sections:
            raise InvalidPack(f"duplicate section type {section_type}")
        if offset < header_size or size > len(data) - offset:
            raise InvalidPack(f"section {section_type} is outside the pack payload")
        sections[section_type] = _SectionRecord(offset, size, count)
        if size:
            occupied.append((offset, offset + size))
    occupied.sort()
    if any(start < previous_end for (_, previous_end), (start, _) in zip(occupied, occupied[1:])):
        raise InvalidPack("pack sections overlap")
    missing = sorted(_REQUIRED_SECTIONS.difference(sections))
    if missing:
        raise InvalidPack(f"pack is missing required section(s): {', '.join(map(str, missing))}")
    if (8 in sections) != (9 in sections):
        raise InvalidPack("asset records and asset data sections must occur together")

    def section_data(section_type: int) -> bytes:
        record = sections[section_type]
        return data[record.offset : record.offset + record.size]

    manifest_record = sections[1]
    builds_record = sections[2]
    symbols_record = sections[3]
    achievements_record = sections[4]
    if manifest_record.count != 1 or manifest_record.size != _MANIFEST.size:
        raise InvalidPack("manifest section has an invalid record count or size")
    if builds_record.size != builds_record.count * _BUILD.size:
        raise InvalidPack("build section size does not match its record count")
    if symbols_record.size != symbols_record.count * _SYMBOL_SIZE:
        raise InvalidPack("symbol section size does not match its record count")
    if achievements_record.size != achievements_record.count * _ACHIEVEMENT_SIZE:
        raise InvalidPack("achievement section size does not match its record count")
    if 8 in sections:
        assets_record = sections[8]
        asset_data_record = sections[9]
        if assets_record.count > 128 or assets_record.size != assets_record.count * _ASSET_SIZE:
            raise InvalidPack("asset section size or count is invalid")
        if asset_data_record.size > 256 * 1024:
            raise InvalidPack("asset data exceeds the pack limit")

    read_string = _string_reader(section_data(7))
    title_id, name, version, license_offset, provenance, reserved = _MANIFEST.unpack(
        section_data(1)
    )
    if reserved != 0:
        raise InvalidPack("manifest reserved field is nonzero")

    builds_data = section_data(2)
    builds: list[PackBuild] = []
    for index in range(builds_record.count):
        fields = _BUILD.unpack_from(builds_data, index * _BUILD.size)
        if fields[5] not in (0, 1):
            raise InvalidPack(f"build {index} has an invalid compatibility flag")
        builds.append(
            PackBuild(
                identifier=read_string(fields[0]),
                region=read_string(fields[1]),
                application_version=read_string(fields[2]),
                update_version=read_string(fields[3]),
                fingerprint=read_string(fields[4]),
                compatible=bool(fields[5]),
            )
        )

    return PackSummary(
        title_id=f"{title_id:016X}",
        game_name=read_string(name),
        profile_version=read_string(version),
        license=read_string(license_offset),
        provenance=read_string(provenance),
        builds=tuple(builds),
        symbol_count=symbols_record.count,
        achievement_count=achievements_record.count,
        asset_count=sections[8].count if 8 in sections else 0,
        format_version=f"{major}.{minor}",
        source_hash=source_hash.hex(),
    )


def inspect_pack(path: str | os.PathLike[str]) -> PackSummary:
    source = Path(path)
    try:
        size = source.stat().st_size
        if size > MAX_PACK_BYTES:
            raise InvalidPack(f"pack exceeds the {MAX_PACK_BYTES}-byte Studio limit")
        return inspect_pack_bytes(source.read_bytes())
    except InvalidPack:
        raise
    except OSError as error:
        raise LibraryError(f"cannot read pack {source}: {error}") from error


def _write_explicit_copy(destination: Path, data: bytes, *, replace: bool) -> None:
    """Write one requested copy, atomically when replacing an existing file."""

    if destination.is_symlink():
        raise LibraryError(f"refusing to replace symbolic link: {destination}")
    if destination.exists():
        if not destination.is_file():
            raise LibraryError(f"copy destination is not a regular file: {destination}")
        if not replace:
            raise LibraryConflict(f"destination already exists: {destination}")

    if not replace:
        created = False
        try:
            with destination.open("xb") as handle:
                created = True
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        return

    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class ProfileLibrary:
    """A directory tree containing manually managed ``.amunpack`` files."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        try:
            self.root = Path(root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise LibraryError(f"cannot resolve library root {root!r}: {error}") from error

    @staticmethod
    def _relative(reference: str | os.PathLike[str]) -> Path:
        text = os.fspath(reference)
        if not isinstance(text, str) or not text or "\0" in text:
            raise LibraryError("library entry path must be a non-empty text path")
        path = Path(text)
        if path.is_absolute() or path.anchor or path.drive or ".." in path.parts:
            raise LibraryError("library entry path must be relative and cannot contain '..'")
        if not path.parts or path.suffix.lower() != PACK_EXTENSION:
            raise LibraryError(f"library entries must use the {PACK_EXTENSION} extension")
        return Path(*path.parts)

    def _path(self, reference: str | os.PathLike[str], *, existing: bool) -> tuple[Path, Path]:
        relative = self._relative(reference)
        candidate = self.root.joinpath(relative)
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise LibraryError(f"cannot resolve library entry {relative}: {error}") from error
        if not resolved.is_relative_to(self.root):
            raise LibraryError("library entry resolves outside the configured root")

        cursor = self.root
        for component in relative.parts:
            cursor = cursor / component
            if cursor.is_symlink():
                raise LibraryError(f"symbolic links are not allowed in library paths: {relative}")
        if existing:
            if not candidate.exists() or not candidate.is_file():
                raise LibraryError(f"library entry does not exist: {relative}")
            return candidate.resolve(strict=True), relative
        return candidate, relative

    def _entry(self, path: Path, relative: Path) -> LibraryEntry:
        try:
            stat = path.stat()
            if stat.st_size > MAX_PACK_BYTES:
                raise InvalidPack(f"pack exceeds the {MAX_PACK_BYTES}-byte Studio limit")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            summary = inspect_pack_bytes(data)
            return LibraryEntry(relative, path, stat.st_size, stat.st_mtime_ns, digest, summary)
        except (OSError, LibraryError) as error:
            try:
                stat = path.stat()
                size, modified_ns = stat.st_size, stat.st_mtime_ns
            except OSError:
                size, modified_ns = 0, 0
            return LibraryEntry(relative, path, size, modified_ns, "", None, str(error))

    def scan(self) -> tuple[LibraryEntry, ...]:
        """Recursively scan regular packs without following or modifying links."""

        if not self.root.exists():
            return ()
        if not self.root.is_dir():
            raise LibraryError(f"library root is not a directory: {self.root}")
        entries: list[LibraryEntry] = []
        visited_directories: set[Path] = set()

        def visit(directory: Path) -> None:
            try:
                resolved_directory = directory.resolve(strict=True)
                if resolved_directory in visited_directories:
                    return
                visited_directories.add(resolved_directory)
                children: Iterable[Path] = sorted(
                    directory.iterdir(), key=lambda item: item.name.casefold()
                )
                for child in children:
                    if child.is_symlink():
                        continue
                    try:
                        resolved_child = child.resolve(strict=True)
                    except (OSError, RuntimeError):
                        continue
                    if not resolved_child.is_relative_to(self.root):
                        # Also covers directory junctions/reparse points that leave
                        # the configured tree even when is_symlink() is false.
                        continue
                    if child.is_dir():
                        visit(child)
                    elif child.is_file() and child.suffix.lower() == PACK_EXTENSION:
                        relative = child.relative_to(self.root)
                        entries.append(self._entry(child, relative))
            except (OSError, RuntimeError) as error:
                raise LibraryError(f"cannot scan library directory {directory}: {error}") from error

        visit(self.root)
        entries.sort(key=lambda entry: entry.key.casefold())
        return tuple(entries)

    def open(self, reference: str | os.PathLike[str]) -> LibraryEntry:
        """Open one contained entry for metadata inspection without writing it."""

        path, relative = self._path(reference, existing=True)
        return self._entry(path, relative)

    def _ensure_import_parent(self, relative: Path) -> None:
        if self.root.exists() and not self.root.is_dir():
            raise LibraryError(f"library root is not a directory: {self.root}")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            cursor = self.root
            for component in relative.parent.parts:
                cursor = cursor / component
                if cursor.is_symlink():
                    raise LibraryError(
                        f"symbolic links are not allowed in library paths: {relative}"
                    )
                if cursor.exists() and not cursor.is_dir():
                    raise LibraryError(f"library path component is not a directory: {cursor}")
                cursor.mkdir(exist_ok=True)
        except LibraryError:
            raise
        except OSError as error:
            raise LibraryError(f"cannot prepare library destination: {error}") from error

    def import_pack(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str] | None = None,
        *,
        replace: bool = False,
    ) -> LibraryEntry:
        """Validate and explicitly copy a local pack into the library."""

        source_input = Path(source).expanduser()
        if source_input.is_symlink():
            raise LibraryError(f"symbolic-link imports are not allowed: {source_input}")
        try:
            source_path = source_input.resolve(strict=True)
        except OSError as error:
            raise LibraryError(f"import source does not exist: {source_input}") from error
        if not source_path.is_file() or source_path.suffix.lower() != PACK_EXTENSION:
            raise LibraryError(f"import source must be a regular {PACK_EXTENSION} file")
        try:
            if source_path.stat().st_size > MAX_PACK_BYTES:
                raise InvalidPack(f"pack exceeds the {MAX_PACK_BYTES}-byte Studio limit")
            data = source_path.read_bytes()
        except InvalidPack:
            raise
        except OSError as error:
            raise LibraryError(f"cannot read import source {source_path}: {error}") from error
        inspect_pack_bytes(data)

        relative = self._relative(destination or source_path.name)
        self._ensure_import_parent(relative)
        destination_path, _ = self._path(relative, existing=False)
        if source_path == destination_path.resolve(strict=False):
            raise LibraryError("import source and destination are the same file")
        try:
            _write_explicit_copy(destination_path, data, replace=replace)
        except LibraryError:
            raise
        except OSError as error:
            raise LibraryError(f"cannot import pack to {destination_path}: {error}") from error
        return self.open(relative)

    def export_pack(
        self,
        reference: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        replace: bool = False,
    ) -> Path:
        """Explicitly copy one valid entry to a caller-selected external path."""

        source_path, _ = self._path(reference, existing=True)
        try:
            data = source_path.read_bytes()
        except OSError as error:
            raise LibraryError(f"cannot read library entry {source_path}: {error}") from error
        inspect_pack_bytes(data)

        destination_text = os.fspath(destination)
        if not isinstance(destination_text, str) or not destination_text or "\0" in destination_text:
            raise LibraryError("export destination must be a non-empty text path")
        expanded = Path(destination_text).expanduser()
        if ".." in expanded.parts:
            raise LibraryError("export destination cannot contain '..'")
        if expanded.suffix.lower() != PACK_EXTENSION:
            raise LibraryError(f"export destination must use the {PACK_EXTENSION} extension")
        if expanded.is_symlink():
            raise LibraryError(f"refusing to export through symbolic link: {expanded}")
        try:
            parent = expanded.parent.resolve(strict=True)
        except OSError as error:
            raise LibraryError(f"export destination directory does not exist: {expanded.parent}") from error
        if not parent.is_dir():
            raise LibraryError(f"export destination parent is not a directory: {parent}")
        destination_path = parent / expanded.name
        if destination_path.resolve(strict=False).is_relative_to(self.root):
            raise LibraryError("export destination must be outside the library; use import to add packs")
        if source_path == destination_path.resolve(strict=False):
            raise LibraryError("export source and destination are the same file")
        try:
            _write_explicit_copy(destination_path, data, replace=replace)
        except LibraryError:
            raise
        except OSError as error:
            raise LibraryError(f"cannot export pack to {destination_path}: {error}") from error
        return destination_path
