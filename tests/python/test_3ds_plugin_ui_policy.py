from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PluginUiPolicyTests(unittest.TestCase):
    def test_information_rows_remain_cursor_selectable(self) -> None:
        source = (ROOT / "3ds" / "plugin" / "main.cpp").read_text(encoding="utf-8")
        for row in ("resultEntry", "inputEntry", "runtimeEntry", "selfTestEntry"):
            self.assertIn(
                f"{row}->CanBeSelected(amun::threeds::kInformationRowsSelectable);",
                source,
            )
        self.assertNotIn("CanBeSelected(false)", source)

    def test_root_b_close_policy_is_applied(self) -> None:
        source = (ROOT / "3ds" / "plugin" / "main.cpp").read_text(encoding="utf-8")
        policy = (
            ROOT / "3ds" / "include" / "amun" / "3ds" / "menu_policy.hpp"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "settings.CloseMenuWithB = amun::threeds::kCloseMenuWithB;", source
        )
        self.assertIn("kCloseMenuWithB = true", policy)
        self.assertIn("kInformationRowsSelectable = true", policy)


    def test_trophy_art_header_matches_studio_pngs(self) -> None:
        import sys

        try:
            import PIL  # noqa: F401
        except ImportError:  # pragma: no cover - Pillow is a dev-only dependency
            self.skipTest("Pillow not installed")
        sys.path.insert(0, str(ROOT / "scripts"))
        from make_trophy_art_header import DEFAULT_OUT, render

        committed = DEFAULT_OUT.read_text(encoding="utf-8")
        self.assertEqual(
            committed,
            render(),
            "trophy_art.hpp is stale: run python scripts/make_trophy_art_header.py",
        )

    def test_unlock_badge_is_wired_and_skips_unranked(self) -> None:
        main = (ROOT / "3ds" / "plugin" / "main.cpp").read_text(encoding="utf-8")
        sink = (ROOT / "3ds" / "runtime" / "event_sink.cpp").read_text(encoding="utf-8")
        overlay = (ROOT / "3ds" / "runtime" / "trophy_overlay.cpp").read_text(encoding="utf-8")
        # Installed only on the observer-running path, never for an inert plugin.
        running = main.index('"observer running; game memory is read-only"')
        self.assertLess(running, main.index("installTrophyOverlay();"))
        self.assertEqual(main.count("installTrophyOverlay();"), 1)
        self.assertIn("showTrophyOverlay(tiers_[head_]);", sink)
        self.assertIn("MetalTier::None", overlay)

if __name__ == "__main__":
    unittest.main()
