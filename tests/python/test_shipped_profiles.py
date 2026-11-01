"""Every set under profiles/ must validate and pass its embedded scenarios."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROFILES = sorted(p.parent for p in (ROOT / "profiles").glob("*/profile.json"))


def amun(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(ROOT / "amun.py"), *arguments],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


class ShippedProfileTests(unittest.TestCase):
    def test_profiles_are_discovered(self) -> None:
        names = {p.name for p in PROFILES}
        self.assertIn("synthetic", names)
        self.assertIn("mario-kart-7-eur", names)

    def test_every_profile_validates_and_passes_its_scenarios(self) -> None:
        for directory in PROFILES:
            with self.subTest(profile=directory.name):
                validated = amun("profile", "validate", str(directory))
                self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
                tested = amun("profile", "test", str(directory))
                self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)

    def test_every_profile_declares_license_and_provenance(self) -> None:
        for directory in PROFILES:
            with self.subTest(profile=directory.name):
                meta = json.loads((directory / "profile.json").read_text(encoding="utf-8"))["profile"]
                self.assertTrue(meta.get("license"), "profile.license is required")
                self.assertTrue(meta.get("provenance"), "profile.provenance is required")

    def test_stable_mk7_profile_is_current(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from make_mk7_stable_profile import DEFAULT_OUT, build

        committed = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))
        self.assertEqual(
            committed, build(),
            "stable profile is stale: run python scripts/make_mk7_stable_profile.py",
        )

    def test_stable_mk7_profile_is_a_strict_subset_of_the_experimental_set(self) -> None:
        stable = json.loads((ROOT / "profiles/mario-kart-7-eur/profile.json").read_text(encoding="utf-8"))
        full = json.loads(
            (ROOT / "profiles/mario-kart-7-eur-progression/profile.json").read_text(encoding="utf-8")
        )
        full_by_id = {a["id"]: a for a in full["achievements"]}
        self.assertEqual(len(stable["achievements"]), 18)
        for achievement in stable["achievements"]:
            original = full_by_id[achievement["id"]]
            self.assertEqual(achievement["points"], original["points"])
            self.assertEqual(achievement["trigger"], original["trigger"])
        for name, symbol in stable["symbols"].items():
            self.assertEqual(symbol, full["symbols"][name])
        self.assertFalse(any(name.startswith("race.") for name in stable["symbols"]))


if __name__ == "__main__":
    unittest.main()
