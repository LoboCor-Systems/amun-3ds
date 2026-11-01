"""Compiler 1.1 -> native parser -> refreshed encoded reads -> ledger replay."""
from pathlib import Path
import argparse
import struct
import subprocess
import sys
import tempfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from compiler.pack import compile_profile, write_pack
from e2e_compiler_runtime import (integration_profile, run_simulator,
                                 TRACE_HEADER, FRAME_HEADER, READ_HEADER)


def trace_bytes(profile_hash, frames):
    encoded = []
    for i, (pointer, old_value, new_value) in enumerate(frames):
        reads = ((0x08001000, struct.pack('<I', pointer ^ 0x75F1B26B)),
                 (0x08002000, bytes([old_value])), (0x08003000, bytes([new_value])))
        payload = b''.join(READ_HEADER.pack(address, len(data), 0) + data for address, data in reads)
        encoded.append(FRAME_HEADER.pack(b'FRAM', len(payload), i * 100, len(reads), 0,
                                          zlib.crc32(payload) & 0xFFFFFFFF) + payload)
    build = b'integration-v1'
    return TRACE_HEADER.pack(b'AMTR', 1, 0, 0x000400000FF40A00, profile_hash,
                             len(encoded), len(build), 0) + build + b''.join(encoded)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulator', required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='amun-pointer-e2e-') as temporary:
        root = Path(temporary)
        profile = integration_profile(root / 'profile.json')
        profile.document['symbols']['synthetic.flag']['resolver'] = {
            'kind': 'pointer_chain', 'address': '0x08001000', 'offsets': [0, 0],
            'xorMasks': ['0x75F1B26B'], 'refresh': True,
        }
        # Requiring value history excludes a first sample and a new allocation.
        profile.document['achievements'][0]['trigger'] = {
            'op': 'increased', 'symbol': 'synthetic.flag'}
        compiled = compile_profile(profile)
        pack = write_pack(compiled, root / 'game.amunpack')
        cases = {
            'new_object_is_not_a_coin': ([(0x08002000, 10, 40), (0x08003000, 10, 40),
                                         (0x08003000, 10, 40)], False),
            'new_object_then_real_increase': ([(0x08002000, 10, 40), (0x08003000, 10, 40),
                                               (0x08003000, 10, 40), (0x08003000, 10, 41)], True),
            'absent_scene_recovers': ([(0x08002000, 10, 40)] + [(0, 10, 40)] * 12 +
                                      [(0x08003000, 10, 40), (0x08003000, 10, 41)], True),
            'null_at_start': ([(0, 10, 40), (0x08002000, 10, 40),
                               (0x08002000, 11, 40)], True),
        }
        for name, (frames, expected) in cases.items():
            trace = root / (name + '.amuntrace')
            trace.write_bytes(trace_bytes(compiled.profile_hash, frames))
            ledger = root / (name + '.amunledger')
            output = run_simulator(args.simulator.resolve(), pack, trace, ledger)
            assert ('UNLOCK first_transition' in output) == expected, (name, output)
            replay = run_simulator(args.simulator.resolve(), pack, trace, ledger)
            assert 'UNLOCK first_transition' not in replay, (name, replay)
        # Independent native parser must reject unversioned/unknown extensions.
        from compiler.pack import HEADER, SECTION, inspect_pack, PackError
        fields = HEADER.unpack_from(compiled.data)
        symbol_offset = next(SECTION.unpack_from(compiled.data, HEADER.size + i * SECTION.size)[1]
                             for i in range(fields[6])
                             if SECTION.unpack_from(compiled.data, HEADER.size + i * SECTION.size)[0] == 3)
        for kind in ('downgraded', 'unknown_flags', 'flags_on_absolute'):
            damaged = bytearray(compiled.data)
            if kind == 'downgraded':
                struct.pack_into('<H', damaged, 6, 0)
            elif kind == 'unknown_flags':
                damaged[symbol_offset + 7] = 4
            else:
                damaged[symbol_offset + 6] = 0
            struct.pack_into('<I', damaged, 12, zlib.crc32(damaged[fields[7]:]) & 0xFFFFFFFF)
            try:
                inspect_pack(damaged)
            except PackError:
                pass
            else:
                raise AssertionError(f'Python accepted {kind}')
            invalid_pack = root / (kind + '.amunpack')
            invalid_pack.write_bytes(damaged)
            result = subprocess.run([str(args.simulator.resolve()), '--pack', str(invalid_pack),
                                     '--trace', str(trace), '--ledger', str(root / (kind + '.ledger'))],
                                    capture_output=True, text=True, timeout=15)
            assert result.returncode != 0 and 'Pack error:' in result.stderr, (kind, result)
        print('Extended pointer pack: 4 native scenarios, 4 ledger replays, 3 parser rejections PASS')


if __name__ == '__main__':
    main()
