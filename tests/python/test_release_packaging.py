from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "package-release.py"


def _write_minimal_3gx(path: Path) -> None:
    """Write the smallest structurally valid pinned-format fixture."""
    header = bytearray(0x94)
    header[:8] = b"3GX$0002"
    struct.pack_into("<I", header, 0x08, 0x00010000)
    struct.pack_into("<I", header, 0x30, 0x3)
    # code/rodata/data offsets followed by their sizes and four zero fields.
    struct.pack_into("<10I", header, 0x58, 0xA0, 0xA4, 0xA4, 4, 0, 0, 0, 0, 0, 0)
    path.write_bytes(header + b"\0" * (0xA0 - len(header)) + b"\x00\x00\xA0\xE1")


def _load_packager():
    specification = importlib.util.spec_from_file_location("amun_release_packager", SCRIPT)
    if specification is None or specification.loader is None:
        raise RuntimeError("could not load release packager")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class ReleasePackagingSafetyTests(unittest.TestCase):
    def test_reviewed_linked_dependency_licenses_match_release_gates(self) -> None:
        packager = _load_packager()
        self.assertEqual(
            packager.CTRPF_LICENSE_SHA256,
            packager._sha256(ROOT / "LICENSES" / "CTRPluginFramework-LICENSE.txt"),
        )
        self.assertEqual(
            packager.LIBCTRU_LICENSE_SHA256,
            packager._sha256(ROOT / "LICENSES" / "libctru-LICENSE.txt"),
        )

    def test_3gx_verifier_checks_structure_beyond_magic(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            temporary = Path(raw_directory)
            plugin = temporary / "valid.3gx"
            _write_minimal_3gx(plugin)
            self.assertEqual(packager._verify_3gx(plugin)["bytes"], 0xA4)

            truncated = temporary / "truncated.3gx"
            truncated.write_bytes(b"3GX$0002")
            with self.assertRaisesRegex(packager.ReleaseError, "truncated"):
                packager._verify_3gx(truncated)

            malformed = bytearray(plugin.read_bytes())
            struct.pack_into("<I", malformed, 0x58, 0xFFFFFFF0)
            malformed_path = temporary / "malformed.3gx"
            malformed_path.write_bytes(malformed)
            with self.assertRaisesRegex(packager.ReleaseError, "out of bounds"):
                packager._verify_3gx(malformed_path)

            unsafe = bytearray(plugin.read_bytes())
            struct.pack_into("<I", unsafe, 0x30, 0x103)  # UsePrivateMemory
            unsafe_path = temporary / "unsafe-policy.3gx"
            unsafe_path.write_bytes(unsafe)
            with self.assertRaisesRegex(packager.ReleaseError, "loader policy"):
                packager._verify_3gx(unsafe_path)

    def test_plugin_bundle_never_claims_hardware_verification(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            temporary = Path(raw_directory)
            plugin = temporary / "AMUN.3gx"
            _write_minimal_3gx(plugin)
            output = temporary / "release"
            arguments = packager.build_parser().parse_args(
                [
                    "--version",
                    "plugin-test",
                    "--output",
                    str(output),
                    "--3gx",
                    str(plugin),
                    "--require-3gx",
                    "--no-zip",
                ]
            )
            stage, _archive = packager.build_release(arguments)
            metadata = json.loads((stage / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "plugin-present-not-hardware-verified")
            self.assertFalse(metadata["hardwareVerified"])
            self.assertTrue(metadata["plugin"]["included"])
            self.assertFalse(metadata["plugin"]["hardwareVerified"])
            self.assertEqual(
                (stage / "sd-root" / "luma" / "plugins" / "default.3gx").read_bytes(),
                plugin.read_bytes(),
            )
            dependency_files = stage / "dependency-patches"
            self.assertTrue((dependency_files / "verify_patched_ctrpf.cmake").is_file())
            self.assertTrue(
                (dependency_files / "patches" / "ctrpf-menu-root-ownership.patch").is_file()
            )
            self.assertIn(
                "verify_patched_ctrpf.cmake",
                (dependency_files / "fetch_pinned_dependencies.cmake").read_text(
                    encoding="utf-8"
                ),
            )

    def test_cli_rejects_traversal_separators_and_leading_dot(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            temporary = Path(raw_directory)
            sentinel = temporary / "sentinel.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            for unsafe in ("../../../victim", r"..\..\..\victim", "nested/version", ".hidden"):
                with self.subTest(version=unsafe):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(SCRIPT),
                            "--version",
                            unsafe,
                            "--output",
                            str(temporary / "output"),
                            "--replace",
                        ],
                        cwd=ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_programmatic_namespace_cannot_bypass_version_validation(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            temporary = Path(raw_directory)
            victim = temporary / "victim"
            victim.mkdir()
            sentinel = victim / "sentinel.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            arguments = packager.build_parser().parse_args([])
            arguments.version = "../../../victim"
            arguments.output = temporary / "output"
            arguments.replace = True
            with self.assertRaises(packager.ReleaseError):
                packager.build_release(arguments)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_replace_is_confined_to_the_selected_version_leaf(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            output = Path(raw_directory) / "release"
            arguments = packager.build_parser().parse_args(
                ["--version", "selected", "--output", str(output), "--no-zip"]
            )
            selected, _archive = packager.build_release(arguments)
            sentinel = output / "AMUN-3DS-vother" / "sentinel.txt"
            sentinel.parent.mkdir()
            sentinel.write_text("preserve", encoding="utf-8")
            outside = Path(raw_directory) / "outside.txt"
            outside.write_text("preserve", encoding="utf-8")

            (selected / "stale.txt").write_text("replace me", encoding="utf-8")
            arguments.replace = True
            rebuilt, _archive = packager.build_release(arguments)

            self.assertEqual(rebuilt, selected)
            self.assertFalse((rebuilt / "stale.txt").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(outside.read_text(encoding="utf-8"), "preserve")

    def test_replace_rejects_a_stage_symlink_that_escapes_output(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            temporary = Path(raw_directory)
            output = temporary / "release"
            output.mkdir()
            victim = temporary / "victim"
            victim.mkdir()
            sentinel = victim / "sentinel.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            stage_link = output / "AMUN-3DS-vselected"
            try:
                stage_link.symlink_to(victim, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks are unavailable: {error}")

            arguments = packager.build_parser().parse_args(
                [
                    "--version",
                    "selected",
                    "--output",
                    str(output),
                    "--no-zip",
                    "--replace",
                ]
            )
            with self.assertRaises(packager.ReleaseError):
                packager.build_release(arguments)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_copy_rejects_symlinked_release_inputs(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            temporary = Path(raw_directory)
            target = temporary / "target.txt"
            target.write_text("outside input", encoding="utf-8")
            link = temporary / "linked.txt"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"file symlinks are unavailable: {error}")
            with self.assertRaises(packager.ReleaseError):
                packager._copy_file(link, temporary / "copy.txt", packager.DEFAULT_EPOCH)
            self.assertFalse((temporary / "copy.txt").exists())

    def test_host_bundle_is_reproducible_and_explicitly_unverified(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            output = Path(raw_directory) / "release"
            arguments = packager.build_parser().parse_args(
                ["--version", "repro", "--output", str(output)]
            )
            stage, archive = packager.build_release(arguments)
            self.assertIsNotNone(archive)
            assert archive is not None
            first_digest = hashlib.sha256(archive.read_bytes()).hexdigest()

            metadata = json.loads((stage / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "host-tools-only")
            self.assertFalse(metadata["hardwareVerified"])
            self.assertFalse(metadata["plugin"]["included"])
            self.assertFalse(metadata["plugin"]["hardwareVerified"])
            self.assertTrue((stage / "NO-3GX.txt").is_file())
            self.assertEqual(
                (stage / "assets" / "branding" / "amun-mark.png").read_bytes(),
                (ROOT / "assets" / "branding" / "amun-mark.png").read_bytes(),
            )
            self.assertFalse((stage / "sd-root" / "luma" / "plugins" / "default.3gx").exists())

            for line in (stage / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
                expected, relative = line.split("  ", 1)
                actual = hashlib.sha256((stage / relative).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, relative)

            arguments.replace = True
            _stage, rebuilt_archive = packager.build_release(arguments)
            self.assertIsNotNone(rebuilt_archive)
            assert rebuilt_archive is not None
            self.assertEqual(
                hashlib.sha256(rebuilt_archive.read_bytes()).hexdigest(), first_digest
            )

    def test_packager_accepts_exactly_the_compilers_pack_version(self) -> None:
        packager = _load_packager()
        sys.path.insert(0, str(ROOT))
        from compiler.pack import PACK_MAJOR, PACK_MINOR

        self.assertEqual(packager.SUPPORTED_PACK_MAJOR, PACK_MAJOR)
        self.assertEqual(packager.SUPPORTED_PACK_MINOR, PACK_MINOR)
        # The shipped MK7 set uses pack 1.1 and must be stageable.
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / "mk7.amunpack"
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "amun.py"), "profile", "build",
                 str(ROOT / "profiles" / "mario-kart-7-eur"), "-o", str(pack)],
                cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            info = packager._inspect_pack(pack)
            self.assertEqual(info["titleId"], "0004000000030700")

    def test_pack_larger_than_runtime_limit_is_rejected_before_read(self) -> None:
        packager = _load_packager()
        with tempfile.TemporaryDirectory() as raw_directory:
            oversized = Path(raw_directory) / "oversized.amunpack"
            with oversized.open("wb") as stream:
                stream.seek(packager.MAX_PACK_BYTES)
                stream.write(b"x")
            with self.assertRaisesRegex(packager.ReleaseError, "exceeds"):
                packager._inspect_pack(oversized)


if __name__ == "__main__":
    unittest.main()
