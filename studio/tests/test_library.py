from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from studio.cli import StudioSettings
from studio.library import (
    InvalidPack,
    LibraryConflict,
    LibraryError,
    ProfileLibrary,
)


HEADER = struct.Struct("<4sHHIIIHH16s")
SECTION = struct.Struct("<IIII")
MANIFEST = struct.Struct("<QIIIII")
BUILD = struct.Struct("<IIIIIB3x")
ACHIEVEMENT = struct.Struct("<IIIIIIIIHBBIIIHHI")


def synthetic_pack(game_name: str = "Library Example") -> bytes:
    strings = bytearray(b"\0")
    offsets: dict[str, int] = {"": 0}

    def add(value: str) -> int:
        if value not in offsets:
            offsets[value] = len(strings)
            strings.extend(value.encode("utf-8") + b"\0")
        return offsets[value]

    manifest = MANIFEST.pack(
        0x0004000001234500,
        add(game_name),
        add("2.1"),
        add("CC0-1.0"),
        add("local test"),
        0,
    )
    builds = BUILD.pack(
        add("eur-1.0"),
        add("EUR"),
        add("1.0"),
        add("0"),
        add("live-text-crc32-v1:00100000:89ABCDEF"),
        0,
    )
    achievement_bytes = bytearray()
    for index in range(3):
        achievement_bytes.extend(
            ACHIEVEMENT.pack(
                add(f"achievement-{index}"),
                add(f"Achievement {index}"),
                add("Synthetic library record"),
                0,
                0,
                0,
                0,
                0,
                5,
                0,
                0,
                0,
                0,
                1,
                1,
                0,
                1,
            )
        )

    sections = (
        (1, manifest, 1),
        (2, builds, 1),
        (3, b"", 0),
        (4, bytes(achievement_bytes), 3),
        (5, b"", 0),
        (6, b"\0", 3),
        (7, bytes(strings), len(offsets)),
    )
    header_size = HEADER.size + len(sections) * SECTION.size
    cursor = header_size
    directory = bytearray()
    payload = bytearray()
    for section_type, section_data, count in sections:
        directory.extend(SECTION.pack(section_type, cursor, len(section_data), count))
        payload.extend(section_data)
        cursor += len(section_data)
    envelope = bytes(directory + payload)
    header = HEADER.pack(
        b"AMUN",
        1,
        0,
        HEADER.size + len(envelope),
        zlib.crc32(payload) & 0xFFFFFFFF,
        0,
        len(sections),
        header_size,
        b"\x11" * 16,
    )
    return header + envelope


class ProfileLibraryTests(unittest.TestCase):
    def test_missing_library_scan_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "not-created-by-scan"
            library = ProfileLibrary(root)
            self.assertEqual((), library.scan())
            self.assertFalse(root.exists())

    def test_import_open_scan_and_export_are_bounded_explicit_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.amunpack"
            source.write_bytes(synthetic_pack())
            library = ProfileLibrary(root / "library")

            imported = library.import_pack(source, "games/example.amunpack")
            self.assertTrue(imported.valid)
            self.assertEqual("Library Example", imported.summary.game_name)
            self.assertEqual(3, imported.summary.achievement_count)
            self.assertEqual("EUR 1.0", imported.summary.builds[0].label)
            self.assertEqual(source.read_bytes(), imported.path.read_bytes())

            scanned = library.scan()
            self.assertEqual(("games/example.amunpack",), tuple(entry.key for entry in scanned))
            before = imported.path.read_bytes()
            opened = library.open("games/example.amunpack")
            self.assertEqual(before, opened.path.read_bytes())

            output = root / "exports" / "copy.amunpack"
            output.parent.mkdir()
            exported = library.export_pack(opened.relative_path, output)
            self.assertEqual(output.resolve(), exported)
            self.assertEqual(before, output.read_bytes())
            self.assertEqual(before, imported.path.read_bytes())

            with self.assertRaises(LibraryConflict):
                library.import_pack(source, "games/example.amunpack")
            with self.assertRaises(LibraryConflict):
                library.export_pack(opened.relative_path, output)

    def test_entry_references_reject_absolute_traversal_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.amunpack"
            source.write_bytes(synthetic_pack())
            library = ProfileLibrary(root / "library")
            library.import_pack(source)

            for unsafe in ("../escape.amunpack", source.resolve()):
                with self.subTest(unsafe=str(unsafe)):
                    with self.assertRaises(LibraryError):
                        library.open(unsafe)
            with self.assertRaises(LibraryError):
                library.import_pack(source, "nested/../../escape.amunpack")
            with self.assertRaises(LibraryError):
                library.export_pack("../source.amunpack", root / "copy.amunpack")
            with self.assertRaises(LibraryError):
                library.export_pack("source.amunpack", library.root / "copy.amunpack")

            external = root / "external.amunpack"
            external.write_bytes(synthetic_pack("External"))
            link = library.root / "linked.amunpack"
            try:
                link.symlink_to(external)
            except OSError:
                pass
            else:
                self.assertNotIn("linked.amunpack", {entry.key for entry in library.scan()})
                with self.assertRaises(LibraryError):
                    library.open("linked.amunpack")

    def test_scan_reports_preexisting_invalid_packs_but_import_rejects_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library_root = root / "library"
            nested = library_root / "nested"
            nested.mkdir(parents=True)
            valid = nested / "valid.amunpack"
            invalid = library_root / "broken.amunpack"
            unrelated = library_root / "notes.json"
            valid.write_bytes(synthetic_pack())
            invalid.write_bytes(b"not a pack")
            unrelated.write_text("{}", encoding="utf-8")
            before = {path: path.read_bytes() for path in (valid, invalid, unrelated)}

            entries = ProfileLibrary(library_root).scan()
            self.assertEqual({"broken.amunpack", "nested/valid.amunpack"}, {item.key for item in entries})
            self.assertEqual(1, sum(item.valid for item in entries))
            self.assertIn("truncated", next(item.error for item in entries if not item.valid))
            self.assertEqual(before, {path: path.read_bytes() for path in before})

            with self.assertRaises(InvalidPack):
                ProfileLibrary(root / "other").import_pack(invalid)
            self.assertFalse((root / "other").exists())

    def test_library_directory_round_trips_in_studio_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings_path = root / "settings.json"
            settings = StudioSettings(library_directory=root / "packs")
            settings.save(settings_path)
            loaded = StudioSettings.load(settings_path)
            self.assertEqual(root / "packs", loaded.library_directory)


if __name__ == "__main__":
    unittest.main()

