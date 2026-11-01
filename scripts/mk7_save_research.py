"""Read-only MK7 save comparison for validating provisional achievement fields.

This never edits a save or claims that a save identifies a game region/build.
Layout reference: mk7re/MK7-Memory SystemSaveData.hpp (CRC and file size).
Cup interpretations are hypotheses; retain the raw index/byte and visible result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

SAVE_SIZE = 0x50D4
CRC_OFFSET = 0x50D0
CUP_OFFSET = 0x70C
COIN_OFFSET = 0x4C28
CUPS = ('mushroom', 'flower', 'star', 'special', 'shell', 'banana', 'leaf', 'lightning')
CLASSES = ('50', '100', '150', 'mirror')


class SaveError(ValueError):
    pass


def inspect_bytes(data: bytes) -> dict:
    if len(data) != SAVE_SIZE:
        raise SaveError(f'Expected {SAVE_SIZE} bytes; got {len(data)}.')
    if data[:4] != b'SSDC':
        raise SaveError('Not a supported plaintext MK7 system save (missing SSDC).')
    version = struct.unpack_from('<I', data, 4)[0]
    if version != 5:
        raise SaveError(f'Unverified save format version {version}; expected 5.')
    stored_crc = struct.unpack_from('<I', data, CRC_OFFSET)[0]
    computed_crc = zlib.crc32(data[:CRC_OFFSET])
    if stored_crc != computed_crc:
        raise SaveError('CRC mismatch: the file may be incomplete or still being saved.')
    return {
        'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': len(data),
        'saveFormatVersion': version,
        'crc32': f'{stored_crc:08X}',
        'candidateLifetimeCoins': struct.unpack_from('<I', data, COIN_OFFSET)[0],
        'candidateCupTableOffset': f'0x{CUP_OFFSET:X}',
        'candidateCupBytes': list(data[CUP_OFFSET:CUP_OFFSET + 32]),
        'warning': 'Save contents do not identify the game build; cup decoding is provisional.',
    }


def read_save(path: Path) -> tuple[bytes, dict]:
    def bounded_read() -> bytes:
        with path.open('rb') as stream:
            return stream.read(SAVE_SIZE + 1)

    data = bounded_read()
    info = inspect_bytes(data)
    if bounded_read() != data:
        raise SaveError('Save changed while being read. Retry after the game finishes saving.')
    return data, {'path': str(path.resolve()), **info}


def candidate_cell(value: int) -> dict:
    rank = (value >> 1) & 7
    valid = (value & 0xC0) == 0 and rank <= 6
    return {
        'raw': f'0x{value:02X}',
        'candidateCompleted': bool(value & 1),
        'candidateTrophy': ('none', 'bronze', 'silver', 'gold')[(value >> 4) & 3],
        'candidateRank': rank,
        'candidateStars': rank - 3 if 4 <= rank <= 6 else 0,
        'candidateEncodingValid': valid,
    }


def compare_bytes(before: bytes, after: bytes) -> dict:
    old_info = inspect_bytes(before)
    new_info = inspect_bytes(after)
    changed = [index for index, (a, b) in enumerate(zip(before, after)) if a != b]
    ranges = []
    for index in changed:
        if ranges and index == ranges[-1][1]:
            ranges[-1][1] += 1
        else:
            ranges.append([index, index + 1])
    cells = []
    for index in range(32):
        address = CUP_OFFSET + index
        if before[address] == after[address]:
            continue
        cells.append({
            'index': index,
            'offset': f'0x{address:X}',
            'cupMajorHypothesis': {'cup': CUPS[index // 4], 'class': CLASSES[index % 4]},
            'classMajorHypothesis': {'cup': CUPS[index % 8], 'class': CLASSES[index // 8]},
            'before': candidate_cell(before[address]),
            'after': candidate_cell(after[address]),
        })
    return {
        'before': old_info,
        'after': new_info,
        'changedByteCount': len(changed),
        'candidateCoinDelta': new_info['candidateLifetimeCoins'] - old_info['candidateLifetimeCoins'],
        'changedCupCells': cells,
        'changedRanges': [
            {'offset': f'0x{start:X}', 'length': end - start,
             'beforePreviewHex': before[start:min(end, start + 32)].hex(),
             'afterPreviewHex': after[start:min(end, start + 32)].hex()}
            for start, end in ranges
        ],
        'releaseGate': 'Compare both system saves and the visible cup/class/trophy/stars. '
                       'A file diff alone does not validate live pointers or a different build.',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inspector = commands.add_parser('inspect', help='Validate and summarize saves without modifying them.')
    inspector.add_argument('saves', nargs='+', type=Path)
    comparison = commands.add_parser('compare', help='Compare an immutable baseline with a later save.')
    comparison.add_argument('before', type=Path)
    comparison.add_argument('after', type=Path)
    for command in (inspector, comparison):
        command.add_argument('--report', type=Path, help='Write a NEW JSON report; never overwrite a file.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = {'saves': [read_save(path)[1] for path in args.saves]}
        else:
            before, old_info = read_save(args.before)
            after, new_info = read_save(args.after)
            result = compare_bytes(before, after)
            result['before']['path'] = old_info['path']
            result['after']['path'] = new_info['path']
        serialized = json.dumps(result, indent=2) + '\n'
        if args.report:
            with args.report.open('x', encoding='utf-8') as stream:
                stream.write(serialized)
        print(serialized, end='')
    except (OSError, SaveError) as exc:
        print(f'MK7 save research: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
