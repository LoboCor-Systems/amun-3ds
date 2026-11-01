"""Bridge the canonical tests/python suite into stdlib discovery.

The repository's top-level ``tests`` directory intentionally contains native
test sources and is not a Python package, so ``unittest discover`` does not
descend into it. The implementation and canonical test source stay in their
requested locations; this small package hook makes the repository test scripts
actually run them.
"""

import unittest


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromName("tests.python.test_3ds_plugin_ui_policy"))
    suite.addTests(loader.loadTestsFromName("tests.python.test_3ds_storage_policy"))
    suite.addTests(loader.loadTestsFromName("tests.python.test_compiler_cli"))
    suite.addTests(loader.loadTestsFromName("tests.python.test_luma_rsp_read"))
    suite.addTests(loader.loadTestsFromName("tests.python.test_release_packaging"))
    return suite
