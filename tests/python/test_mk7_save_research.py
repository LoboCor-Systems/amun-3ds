"""Synthetic parser checks, not evidence that candidate trophy fields are correct."""
import contextlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from scripts.mk7_save_research import (
    COIN_OFFSET, CRC_OFFSET, CUP_OFFSET, SAVE_SIZE, SaveError,
    compare_bytes, inspect_bytes, main, read_save,
)


def save(*, coins=0, cell=None):
    data = bytearray(SAVE_SIZE)
    data[:4] = b'SSDC'
    struct.pack_into('<I', data, 4, 5)
    struct.pack_into('<I', data, COIN_OFFSET, coins)
    if cell is not None:
        data[CUP_OFFSET + cell[0]] = cell[1]
    struct.pack_into('<I', data, CRC_OFFSET, zlib.crc32(data[:CRC_OFFSET]))
    return bytes(data)


class SaveResearchTests(unittest.TestCase):
    def test_plaintext_crc_and_raw_fields(self):
        info = inspect_bytes(save(coins=67, cell=(0, 0x3B)))
        self.assertEqual(info['candidateLifetimeCoins'], 67)
        self.assertEqual(info['candidateCupBytes'][0], 0x3B)
        self.assertIn('provisional', info['warning'])

    def test_rejects_truncation_extra_bytes_magic_version_and_crc(self):
        good = save()
        bad_version = bytearray(good)
        bad_version[4] = 6
        bad_crc = bytearray(good)
        bad_crc[0x40] = 1
        for invalid in (good[:-1], good + b'\0', b'NOPE' + good[4:], bad_version, bad_crc):
            with self.subTest(size=len(invalid)):
                with self.assertRaises(SaveError):
                    inspect_bytes(invalid)

    def test_order_hypotheses_stay_distinct(self):
        comparison = compare_bytes(save(), save(coins=24, cell=(16, 0x3B)))
        self.assertEqual(comparison['candidateCoinDelta'], 24)
        cell = comparison['changedCupCells'][0]
        self.assertEqual(cell['offset'], '0x71C')
        self.assertEqual(cell['cupMajorHypothesis'], {'cup': 'shell', 'class': '50'})
        self.assertEqual(cell['classMajorHypothesis'], {'cup': 'mushroom', 'class': '150'})
        self.assertEqual(cell['after']['candidateTrophy'], 'gold')
        self.assertEqual(cell['after']['candidateStars'], 2)

    def test_unchanged_save(self):
        result = compare_bytes(save(), save())
        self.assertEqual(result['changedByteCount'], 0)
        self.assertEqual(result['changedRanges'], [])
        self.assertEqual(result['changedCupCells'], [])

    def test_non_cup_changes_do_not_invent_trophies(self):
        result = compare_bytes(save(), save(coins=5))
        self.assertEqual(result['changedCupCells'], [])
        self.assertEqual(result['candidateCoinDelta'], 5)

    def test_changing_save_is_rejected(self):
        with patch.object(Path, 'open', side_effect=[io.BytesIO(save()), io.BytesIO(save(coins=1))]):
            with self.assertRaisesRegex(SaveError, 'changed while'):
                read_save(Path('unused.dat'))

    def test_cli_report_is_exclusive_and_save_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'system0.dat'
            report = root / 'inspection.json'
            data = save(coins=12)
            source.write_bytes(data)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['inspect', str(source), '--report', str(report)]), 0)
                original_report = report.read_bytes()
                self.assertEqual(main(['inspect', str(source), '--report', str(report)]), 1)
                self.assertEqual(main(['inspect', str(source), '--report', str(source)]), 1)
            self.assertEqual(source.read_bytes(), data)
            self.assertEqual(report.read_bytes(), original_report)


if __name__ == '__main__':
    unittest.main()
