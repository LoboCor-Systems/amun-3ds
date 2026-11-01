import copy
import struct
import unittest

from compiler.diagnostics import CompilationFailed
from compiler.pack import compile_profile, inspect_pack, PackError
from tests.python.test_compiler_cli import no_asset_document


class PointerResolverTests(unittest.TestCase):
    def document(self):
        doc = no_asset_document()
        first = next(iter(doc['symbols']))
        doc['symbols'][first]['resolver'] = {
            'kind': 'pointer_chain', 'address': '0x006789B8',
            'offsets': [16, 520, 40, 19696],
            'xorMasks': [0, '0x75F1B26B', 0], 'refresh': True,
        }
        return doc, first

    def test_extended_round_trip_and_version_gate(self):
        doc, first = self.document()
        compiled = compile_profile(doc)
        info = inspect_pack(compiled.data)
        self.assertEqual(info['version'], '1.1')
        resolver = next(s for s in info['symbols'] if s['name'] == first)['resolver']
        self.assertEqual(resolver['xorMasks'], [0, 0x75F1B26B, 0])
        self.assertTrue(resolver['refresh'])
        self.assertEqual(resolver['offsets'], [16, 520, 40, 19696])
        downgraded = bytearray(compiled.data)
        struct.pack_into('<H', downgraded, 6, 0)
        with self.assertRaisesRegex(PackError, 'requires pack 1.1'):
            inspect_pack(downgraded)

    def test_legacy_packs_stay_version_one_zero(self):
        doc, first = self.document()
        resolver = doc['symbols'][first]['resolver']
        resolver.pop('xorMasks')
        resolver.pop('refresh')
        self.assertEqual(inspect_pack(compile_profile(doc).data)['version'], '1.0')

    def test_limits_and_bad_options_rejected(self):
        doc, first = self.document()
        for change in ({'xorMasks': [0]}, {'xorMasks': [0, -1, 0]}, {'refresh': 1},
                       {'offsets': [0] * 17}, {'kind': 'absolute'}):
            bad = copy.deepcopy(doc)
            bad['symbols'][first]['resolver'].update(change)
            with self.subTest(change=change), self.assertRaises(CompilationFailed):
                compile_profile(bad)

    def test_sixteen_offsets_supported_with_explicit_version(self):
        doc, first = self.document()
        resolver = doc['symbols'][first]['resolver']
        resolver['offsets'] = [0] * 16
        resolver['xorMasks'] = [0] * 15
        self.assertEqual(inspect_pack(compile_profile(doc).data)['version'], '1.1')


if __name__ == '__main__':
    unittest.main()
