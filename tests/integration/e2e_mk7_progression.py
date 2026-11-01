"""Replay the MK7 progression candidate with synthetic encoded pointer graphs."""
import argparse
from pathlib import Path
import re
import struct
import tempfile
import zlib

from e2e_compiler_runtime import (FRAME_HEADER, READ_HEADER, REPOSITORY_ROOT,
                                 TRACE_HEADER, run_simulator)
from compiler.pack import compile_profile, write_pack
from compiler.profile import load_profile
from tests.python.test_mk7_progression import progression_scenarios

# Independent fake allocations: catches accidental hardcoded live-heap use.
FAKE_HEAP_BASE = 0x08002000
FAKE_NODE_STRIDE = 0x10000
SCALAR_FORMATS = {'u8': '<B', 's8': '<b', 'i8': '<b', 'u16': '<H', 's16': '<h', 'i16': '<h',
                  'u32': '<I', 's32': '<i', 'i32': '<i'}


def _int(text):
    return int(text, 0) if isinstance(text, str) else int(text)


class PointerGraph:
    """Lay out every pointer_chain symbol of the profile as one shared fake object graph.

    Chains with a common (root, offset...) prefix share the same fake object, exactly as the
    live game would, so every symbol (save, race, respawn/underwater/flying logs, ...) resolves.
    """

    def __init__(self, symbols):
        self.chains = {}
        nodes = {}
        for name, symbol in symbols.items():
            resolver = symbol.get('resolver', {})
            if resolver.get('kind') == 'derived':
                continue
            if resolver.get('kind') != 'pointer_chain':
                raise AssertionError(f'{name}: unsupported resolver {resolver.get("kind")!r}')
            if symbol['type'] not in SCALAR_FORMATS:
                raise AssertionError(f'{name}: unsupported type {symbol["type"]!r}')
            root = _int(resolver['address'])
            offsets = [_int(o) for o in resolver['offsets']]
            masks = [_int(m) for m in resolver.get('xorMasks', [])] or [0] * (len(offsets) - 1)
            path = (root,)
            for offset in offsets[:-1]:
                path += (offset,)
                if path not in nodes:
                    nodes[path] = FAKE_HEAP_BASE + len(nodes) * FAKE_NODE_STRIDE
            self.chains[name] = (root, offsets, masks, symbol['type'])
        self.nodes = nodes

    def frame_reads(self, values):
        memory = {}

        def put(address, data, owner):
            for index, byte in enumerate(data):
                previous = memory.setdefault(address + index, (byte, owner))
                if previous[0] != byte:
                    raise AssertionError(f'{owner} overlaps {previous[1]} at {address + index:#x}')

        for name, (root, offsets, masks, kind) in self.chains.items():
            if name not in values:
                continue  # leave the leaf unreadable, like an unsampled symbol
            parent, path = root, (root,)
            for depth, offset in enumerate(offsets[:-1]):
                path += (offset,)
                node = self.nodes[path]
                put(parent + offset, struct.pack('<I', node ^ masks[depth]), f'{name} ptr{depth}')
                parent = node
            put(parent + offsets[-1], struct.pack(SCALAR_FORMATS[kind], values[name]), name)

        reads, run_start, run = [], None, bytearray()
        for address in sorted(memory):
            if run_start is not None and address == run_start + len(run) and len(run) < 4096:
                run.append(memory[address][0])
                continue
            if run_start is not None:
                reads.append((run_start, bytes(run)))
            run_start, run = address, bytearray([memory[address][0]])
        if run_start is not None:
            reads.append((run_start, bytes(run)))
        return reads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulator', required=True, type=Path)
    args = parser.parse_args()
    loaded = load_profile(REPOSITORY_ROOT / 'profiles/mario-kart-7-eur-progression/profile.json')
    compiled = compile_profile(loaded)
    graph = PointerGraph(loaded.document['symbols'])
    scenarios = loaded.document['tests'] + progression_scenarios(loaded.document)
    with tempfile.TemporaryDirectory(prefix='amun-mk7-progression-e2e-') as temporary:
        root = Path(temporary)
        pack = write_pack(compiled, root / 'game.amunpack')
        build = loaded.document['game']['builds'][0]['id'].encode('ascii')
        for index, scenario in enumerate(scenarios):
            frames = []
            for frame in scenario['frames']:
                reads = graph.frame_reads(frame['values'])
                payload = b''.join(READ_HEADER.pack(address, len(data), 0) + data
                                   for address, data in reads)
                frames.append(FRAME_HEADER.pack(b'FRAM', len(payload), frame['timeMs'], len(reads), 0,
                                                zlib.crc32(payload) & 0xFFFFFFFF) + payload)
            trace = root / 'synthetic.amuntrace'
            trace.write_bytes(TRACE_HEADER.pack(b'AMTR', 1, 0, 0x0004000000030700,
                                                compiled.profile_hash, len(frames), len(build), 0)
                              + build + b''.join(frames))
            ledger = root / f'{index}.amunledger'
            first = run_simulator(args.simulator.resolve(), pack, trace, ledger)
            observed = set(re.findall(r'^UNLOCK (\S+)', first, re.MULTILINE))
            assert observed == set(scenario['expectUnlocked']), (scenario['name'], first)
            replay = run_simulator(args.simulator.resolve(), pack, trace, ledger)
            assert not re.search(r'^UNLOCK ', replay, re.MULTILINE), (scenario['name'], replay)
    print(f'MK7 progression candidate: {len(scenarios)} native scenarios + '
          f'{len(scenarios)} ledger replays PASS')


if __name__ == '__main__':
    main()