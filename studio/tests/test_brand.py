from __future__ import annotations

from pathlib import Path
import struct
import unittest

from studio.brand import BRAND_MARK_64, BRAND_MARK_256


def _png_dimensions(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG with an IHDR: {path}")
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, color_type


class BrandAssetTests(unittest.TestCase):
    def test_studio_marks_are_bounded_square_rgba_pngs(self) -> None:
        self.assertEqual(_png_dimensions(BRAND_MARK_64), (64, 64, 6))
        self.assertEqual(_png_dimensions(BRAND_MARK_256), (256, 256, 6))
        self.assertLess(BRAND_MARK_64.stat().st_size, 16 * 1024)
        self.assertLess(BRAND_MARK_256.stat().st_size, 128 * 1024)


if __name__ == "__main__":
    unittest.main()
