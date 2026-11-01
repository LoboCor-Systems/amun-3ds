"""Platform metal tiers: shared Python table, C++/Hub copies, and bundled art."""

from __future__ import annotations

from pathlib import Path
import re
import struct
import unittest

from compiler.metal_tiers import (
    BANDS,
    MAX_POINTS,
    PALETTE,
    MetalTier,
    band_range,
    format_tier_counts,
    metal_label,
    metal_tier,
    points_label,
    tier_counts,
)
from hub import metal_tiers as hub_metal_tiers

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "core" / "include" / "amun" / "metal_tier.hpp"
SOURCE_ART = ROOT / "assets" / "branding" / "metal-tiers"
STUDIO_ART = ROOT / "studio" / "assets" / "metal-tiers"


def _png_header(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG: {path}")
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, color_type


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class BandTests(unittest.TestCase):
    def test_documented_bands(self) -> None:
        expected = {
            MetalTier.COPPER: (1, 4),
            MetalTier.BRONZE: (5, 9),
            MetalTier.SILVER: (10, 14),
            MetalTier.ELECTRUM: (15, 24),
            MetalTier.GOLD: (25, 49),
            MetalTier.PLATINUM: (50, 99),
            MetalTier.RHODIUM: (100, MAX_POINTS),
        }
        for tier, (low, high) in expected.items():
            self.assertEqual(band_range(tier), (low, high))
            self.assertIs(metal_tier(low), tier)
            self.assertIs(metal_tier(high), tier)
            self.assertIsNot(metal_tier(low - 1), tier)

    def test_unranked_and_invalid_values(self) -> None:
        for value in (0, -5, None, "10", 10.0, True):
            self.assertIs(metal_tier(value), MetalTier.NONE)
        self.assertEqual(metal_label(0), "")
        self.assertEqual(points_label(10), "10 (Silver)")
        self.assertEqual(points_label(0), "0")

    def test_counts_and_format(self) -> None:
        counts = tier_counts([0, 0, 5, 10, 10, 25])
        self.assertEqual(counts[MetalTier.NONE], 2)
        self.assertEqual(format_tier_counts(counts), "Bronze 1, Silver 2, Gold 1")


class CopyConsistencyTests(unittest.TestCase):
    def test_cpp_header_matches_python_table(self) -> None:
        source = HEADER.read_text(encoding="utf-8")
        rows = re.findall(
            r"\{MetalTier::(\w+),\s*(\d+)U,\s*\"(\w+)\",\s*"
            r"\{\s*(\d+),\s*(\d+),\s*(\d+)\},\s*\{\s*(\d+),\s*(\d+),\s*(\d+)\},\s*"
            r"\{\s*(\d+),\s*(\d+),\s*(\d+)\},\s*\{\s*(\d+),\s*(\d+),\s*(\d+)\}\}",
            source,
        )
        self.assertEqual(len(rows), len(BANDS))
        for row, (tier, lower) in zip(rows, BANDS):
            enum_name, minimum, name, *rgb = row
            values = [int(v) for v in rgb]
            colors = PALETTE[tier]
            self.assertEqual(enum_name.upper(), tier.name)
            self.assertEqual(int(minimum), lower)
            self.assertEqual(name, tier.label)
            self.assertEqual(
                values,
                [*colors.highlight, *colors.mid, *colors.shadow, *colors.ink],
                f"C++ palette for {tier.label} drifted from compiler/metal_tiers.py",
            )

    def test_hub_copy_matches_python_table(self) -> None:
        self.assertEqual(
            hub_metal_tiers.BANDS, tuple((tier.label, lower) for tier, lower in BANDS)
        )
        for points in (0, 1, 4, 5, 9, 10, 14, 15, 24, 25, 49, 50, 99, 100, MAX_POINTS):
            expected = metal_label(points) or None
            self.assertEqual(hub_metal_tiers.metal_name(points), expected)


class PaletteTests(unittest.TestCase):
    def test_toast_text_is_readable_on_tier_ink(self) -> None:
        for tier, colors in PALETTE.items():
            self.assertGreaterEqual(_contrast(colors.highlight, colors.ink), 7.0, tier.label)

    def test_neighbouring_and_lookalike_metals_stay_distinct(self) -> None:
        def distance(a: MetalTier, b: MetalTier) -> float:
            return sum((x - y) ** 2 for x, y in zip(PALETTE[a].mid, PALETTE[b].mid)) ** 0.5

        pairs = [(BANDS[i][0], BANDS[i + 1][0]) for i in range(len(BANDS) - 1)]
        pairs += [(MetalTier.SILVER, MetalTier.PLATINUM), (MetalTier.SILVER, MetalTier.RHODIUM)]
        for a, b in pairs:
            self.assertGreater(distance(a, b), 45.0, f"{a.label} vs {b.label}")

    def test_platinum_reads_cool_and_silver_neutral(self) -> None:
        r, g, b = PALETTE[MetalTier.SILVER].mid
        self.assertLessEqual(max(r, g, b) - min(r, g, b), 10)
        r, g, b = PALETTE[MetalTier.PLATINUM].mid
        self.assertGreater(b - r, 60)


class AssetTests(unittest.TestCase):
    def test_source_and_small_trophies_exist(self) -> None:
        for tier in MetalTier:
            if tier is MetalTier.NONE:
                continue
            self.assertEqual(_png_header(SOURCE_ART / f"{tier.slug}.png"), (64, 64, 6))
            for size in (16, 24):
                self.assertEqual(_png_header(STUDIO_ART / f"{tier.slug}-{size}.png"), (size, size, 6))

    def test_alpha_is_binary_for_rgba5551(self) -> None:
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - Pillow is a dev-only dependency
            self.skipTest("Pillow not installed")
        for path in sorted(SOURCE_ART.glob("*.png")) + sorted(STUDIO_ART.glob("*.png")):
            with Image.open(path) as image:
                histogram = image.convert("RGBA").getchannel("A").histogram()
            partial = [level for level in range(1, 255) if histogram[level]]
            self.assertEqual(partial, [], path.name)


class StudioSummaryTests(unittest.TestCase):
    def test_studio_metal_summary_line(self) -> None:
        try:
            from studio.app import achievement_metal_summary
        except ImportError:  # pragma: no cover - tkinter missing
            self.skipTest("tkinter not available")
        line = achievement_metal_summary([{"points": 5}, {"points": 10}, {"points": 0}, "bad"])
        self.assertEqual(line, "Metals: Bronze 1, Silver 1 · 1 unranked")
        self.assertEqual(achievement_metal_summary([]), "Metals: none")


if __name__ == "__main__":
    unittest.main()
