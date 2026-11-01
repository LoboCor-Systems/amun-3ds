from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ThreeDsStoragePolicyTests(unittest.TestCase):
    def test_existing_ledger_append_establishes_eof_before_exact_write(self) -> None:
        source = (ROOT / "3ds" / "storage" / "ctrpf_ledger.cpp").read_text(
            encoding="utf-8"
        )
        seek = "file.Seek(0, CTRPluginFramework::File::END)"
        cursor = "file.Tell() == validBytes_"
        record_write = "writeExact(file, record.data(), record.size())"
        self.assertIn(seek, source)
        self.assertIn(cursor, source)
        self.assertIn(record_write, source)
        self.assertLess(source.index(seek), source.index(record_write))
        self.assertRegex(
            source,
            re.compile(
                r"record\.insert\(record\.end\(\), header\.begin\(\), header\.end\(\)\);"
                r".*record\.insert\(record\.end\(\), payload\.begin\(\), payload\.end\(\)\);"
                r".*writeExact\(file, record\.data\(\), record\.size\(\)\)",
                re.DOTALL,
            ),
        )

    def test_thread_patch_never_raw_frees_a_possibly_running_thread(self) -> None:
        patch = (
            ROOT
            / "cmake"
            / "3ds"
            / "patches"
            / "ctrpf-threadex-safe-destruction.patch"
        ).read_text(encoding="utf-8")
        fetcher = (ROOT / "cmake" / "3ds" / "fetch_pinned_dependencies.cmake").read_text(
            encoding="utf-8"
        )
        verifier = (ROOT / "cmake" / "3ds" / "verify_patched_ctrpf.cmake").read_text(
            encoding="utf-8"
        )
        self.assertIn("+            if (_thread->finished)", patch)
        self.assertIn("+                threadFree(_thread);", patch)
        self.assertNotIn("+            std::free(_thread);", patch)
        self.assertIn("ctrpf-threadex-safe-destruction.patch", fetcher)
        self.assertIn('"std::free(_thread);" unsafe_thread_free', verifier)

    def test_plgldr_patch_treats_missing_event_channel_as_idle(self) -> None:
        patch = (
            ROOT
            / "cmake"
            / "3ds"
            / "patches"
            / "ctrpf-plgldr-null-event-guard.patch"
        ).read_text(encoding="utf-8")
        fetcher = (ROOT / "cmake" / "3ds" / "fetch_pinned_dependencies.cmake").read_text(
            encoding="utf-8"
        )
        verifier = (ROOT / "cmake" / "3ds" / "verify_patched_ctrpf.cmake").read_text(
            encoding="utf-8"
        )
        self.assertIn("+    if (plgEvent == NULL)", patch)
        self.assertIn("+        return PLG_OK;", patch)
        self.assertIn("+    if (plgEvent == NULL || plgReply == NULL)", patch)
        self.assertIn("ctrpf-plgldr-null-event-guard.patch", fetcher)
        self.assertIn("null_safe_event_fetch", verifier)
        self.assertIn("null_safe_event_reply", verifier)


if __name__ == "__main__":
    unittest.main()
