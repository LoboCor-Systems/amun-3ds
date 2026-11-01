from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from studio.cli import CliHooks, StudioSettings, format_command, parse_command
from studio.deployment import (
    DeploymentConflict,
    DeploymentError,
    DeploymentTransaction,
    SdDeployer,
    detect_sd_cards,
)
from studio.project import ProfileProject, ProjectError
from studio.scanner import MemorySnapshot, ScanError, SnapshotScanner, VALUE_TYPES


class ProjectTests(unittest.TestCase):
    def test_create_edit_save_and_reopen_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = ProfileProject.create(temporary)
            project.replace_symbol(
                "player.hp",
                {"type": "u16", "resolver": {"kind": "absolute", "address": "0x8123456"}},
            )
            project.replace_achievement(
                {"id": "alive", "title": "Still Standing", "points": 5, "trigger": {}}
            )
            saved = project.save()

            reopened = ProfileProject.open(temporary)
            self.assertEqual(saved, reopened.profile_path)
            self.assertEqual("player.hp", reopened.symbols()[0][0])
            self.assertEqual("alive", reopened.achievements()[0]["id"])
            self.assertFalse(reopened.dirty)

    def test_invalid_json_never_replaces_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = ProfileProject.create(temporary)
            project.save()
            original = project.profile_path.read_bytes()
            with self.assertRaises(ProjectError):
                project.save('{"symbols":')
            self.assertEqual(original, project.profile_path.read_bytes())

    def test_directory_with_ambiguous_json_requires_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.json").write_text("{}", encoding="utf-8")
            (root / "two.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "multiple JSON"):
                ProfileProject.open(root)


class CliTests(unittest.TestCase):
    def test_cli_hook_appends_profile_contract_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hooks = CliHooks(
                (
                    sys.executable,
                    "-c",
                    "import json,sys; print(json.dumps(sys.argv[1:]))",
                )
            )
            result = hooks.validate(root)
            self.assertTrue(result.ok)
            self.assertEqual(["profile", "validate", str(root.resolve())], json.loads(result.stdout))

    def test_command_text_round_trip(self) -> None:
        command = (sys.executable, "-m", "example module")
        self.assertEqual(command, parse_command(format_command(command)))

    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            original = StudioSettings((sys.executable, "-m", "amun"), 9.5, Path(temporary) / "backups")
            original.save(path)
            loaded = StudioSettings.load(path)
            self.assertEqual(original.cli_command, loaded.cli_command)
            self.assertEqual(9.5, loaded.cli_timeout_seconds)
            self.assertEqual(original.backup_directory, loaded.backup_directory)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capture.amunsnap"
            snapshot = MemorySnapshot(b"\x00\x01\x7f\xff", 0x08000000, "capture")
            snapshot.save(path)
            loaded = MemorySnapshot.load(path)
            self.assertEqual(snapshot.data, loaded.data)
            self.assertEqual(0x08000000, loaded.base_address)
            self.assertEqual("capture", loaded.name)

            damaged = bytearray(path.read_bytes())
            damaged[-1] ^= 0x80
            path.write_bytes(damaged)
            with self.assertRaisesRegex(ScanError, "checksum"):
                MemorySnapshot.load(path)

    def test_exact_scans_decode_every_required_little_endian_type(self) -> None:
        examples = {
            "u8": (1, 250),
            "s8": (-3, 100),
            "u16": (0x1234, 0xABCD),
            "s16": (-1234, 2345),
            "u32": (0x12345678, 0xF0000000),
            "s32": (-12345678, 12345678),
            "f32": (1.25, -3.5),
        }
        for type_name, values in examples.items():
            with self.subTest(type_name=type_name):
                codec = VALUE_TYPES[type_name]
                data = struct.pack("<" + codec.struct_code * 2, *values)
                scanner = SnapshotScanner()
                count = scanner.start(
                    MemorySnapshot(data, 0x1000), type_name, "exact", value=values[1], stride=codec.size
                )
                self.assertEqual(1, count)
                self.assertEqual(0x1000 + codec.size, scanner.results()[0].address)
                self.assertEqual(values[1], scanner.results()[0].current)

    def _u16_refinement(self, mode: str, **arguments: int) -> SnapshotScanner:
        before = MemorySnapshot(struct.pack("<4H", 10, 20, 30, 0b0010), 0x2000)
        after = MemorySnapshot(struct.pack("<4H", 15, 20, 25, 0b1010), 0x2000)
        scanner = SnapshotScanner()
        scanner.start(before, "u16", "unknown", stride=2)
        scanner.refine(after, mode, **arguments)
        return scanner

    def test_relative_scan_modes(self) -> None:
        cases = (
            ("changed", {}, [0x2000, 0x2004, 0x2006]),
            ("unchanged", {}, [0x2002]),
            ("increased", {}, [0x2000, 0x2006]),
            ("decreased", {}, [0x2004]),
            ("by", {"value": 5}, [0x2000]),
            ("exact", {"value": 20}, [0x2002]),
            ("between", {"value": 15, "second": 25}, [0x2000, 0x2002, 0x2004]),
            ("bit-changed", {"mask": 0b1000}, [0x2006]),
        )
        for mode, arguments, expected in cases:
            with self.subTest(mode=mode):
                scanner = self._u16_refinement(mode, **arguments)
                self.assertEqual(expected, scanner.candidates)

    def test_changed_uses_float_bits_so_stable_nan_is_unchanged(self) -> None:
        nan_bits = struct.pack("<I", 0x7FC00001)
        before = MemorySnapshot(nan_bits)
        after = MemorySnapshot(nan_bits)
        scanner = SnapshotScanner()
        scanner.start(before, "f32", "unknown", stride=4)
        scanner.refine(after, "unchanged")
        self.assertEqual([0], scanner.candidates)

    def test_candidate_limit_prevents_accidental_huge_unknown_scan(self) -> None:
        scanner = SnapshotScanner(max_candidates=3)
        with self.assertRaisesRegex(ScanError, "limit"):
            scanner.start(MemorySnapshot(b"\0" * 10), "u8", "unknown")


class DeploymentTests(unittest.TestCase):
    def _trees(self, temporary: str) -> tuple[Path, Path, Path]:
        root = Path(temporary)
        source = root / "source"
        sd = root / "sd"
        backups = root / "backups"
        (source / "luma" / "plugins").mkdir(parents=True)
        (source / "amun").mkdir(parents=True)
        (sd / "amun").mkdir(parents=True)
        (sd / "photos").mkdir(parents=True)
        (source / "luma" / "plugins" / "default.3gx").write_bytes(b"plugin-v1")
        (source / "amun" / "game.amunpack").write_bytes(b"pack-v2")
        (sd / "amun" / "game.amunpack").write_bytes(b"pack-v1")
        (sd / "photos" / "unrelated.jpg").write_bytes(b"do-not-touch")
        return source, sd, backups

    def test_deploy_and_rollback_touch_only_packaged_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, sd, backups = self._trees(temporary)
            deployer = SdDeployer(backups)
            transaction = deployer.deploy(source, sd)

            self.assertEqual("complete", transaction.status)
            self.assertEqual(b"plugin-v1", (sd / "luma" / "plugins" / "default.3gx").read_bytes())
            self.assertEqual(b"pack-v2", (sd / "amun" / "game.amunpack").read_bytes())
            self.assertEqual(b"do-not-touch", (sd / "photos" / "unrelated.jpg").read_bytes())
            self.assertTrue(transaction.manifest_path.is_file())
            self.assertFalse(transaction.directory.is_relative_to(sd))

            restored = deployer.rollback(transaction)
            self.assertEqual("rolled_back", restored.status)
            self.assertFalse((sd / "luma" / "plugins" / "default.3gx").exists())
            self.assertEqual(b"pack-v1", (sd / "amun" / "game.amunpack").read_bytes())
            self.assertEqual(b"do-not-touch", (sd / "photos" / "unrelated.jpg").read_bytes())

    def test_rollback_conflict_is_preflighted_without_partial_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, sd, backups = self._trees(temporary)
            deployer = SdDeployer(backups)
            transaction = deployer.deploy(source, sd)
            deployed_pack = sd / "amun" / "game.amunpack"
            deployed_pack.write_bytes(b"user-modified-after-deploy")

            with self.assertRaises(DeploymentConflict):
                deployer.rollback(transaction)
            self.assertEqual(b"user-modified-after-deploy", deployed_pack.read_bytes())
            self.assertEqual(b"plugin-v1", (sd / "luma" / "plugins" / "default.3gx").read_bytes())

    def test_transaction_can_be_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, sd, backups = self._trees(temporary)
            transaction = SdDeployer(backups).deploy(source, sd)
            loaded = DeploymentTransaction.load(transaction.manifest_path)
            self.assertEqual(transaction.identifier, loaded.identifier)
            self.assertEqual(len(transaction.entries), len(loaded.entries))

    def test_backup_directory_inside_sd_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, sd, _ = self._trees(temporary)
            with self.assertRaisesRegex(DeploymentError, "outside"):
                SdDeployer(sd / ".backups").deploy(source, sd)

    def test_detection_scores_3ds_markers_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            likely = root / "likely"
            plain = root / "plain"
            (likely / "luma").mkdir(parents=True)
            plain.mkdir()
            candidates = detect_sd_cards((plain, likely))
            self.assertEqual(likely.resolve(), candidates[0].root)
            self.assertGreater(candidates[0].score, candidates[1].score)
            self.assertEqual([], list(plain.iterdir()))


if __name__ == "__main__":
    unittest.main()
