from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "tuya_local_ble"
    / "tuya_ble"
    / "diagnostics_350k.py"
)
spec = importlib.util.spec_from_file_location("diagnostics_350k", PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Test350KProtocolHelpers(unittest.TestCase):
    def test_confirmed_dp46_bool_payload(self):
        self.assertEqual(
            module.build_v4_bool_data(46, True),
            bytes.fromhex("00000000012e01000101"),
        )

    def test_enum_payload(self):
        self.assertEqual(
            module.build_v4_enum_data(31, 2),
            bytes.fromhex("00000000011f04000102"),
        )

    def test_dp71_shape_only(self):
        payload = bytes.fromhex("000000000147000013") + b"x" * 19
        self.assertTrue(module.valid_dp71_payload_shape(payload))
        self.assertFalse(module.valid_dp71_payload_shape(payload[:-1]))

    def test_sequence_gap_and_wrap(self):
        self.assertEqual(module.compute_sequence_gap(10, 11), (0, False))
        self.assertEqual(module.compute_sequence_gap(10, 14), (3, False))
        self.assertEqual(module.compute_sequence_gap(10, 5000), (0, True))
        self.assertEqual(module.compute_sequence_gap((1 << 40) - 1, 0), (0, False))

    def test_write_size_fallback_and_cap(self):
        self.assertEqual(module.normalize_write_chunk_size(20), 20)
        self.assertEqual(module.normalize_write_chunk_size(19), 20)
        self.assertEqual(module.normalize_write_chunk_size(68), 68)
        self.assertEqual(module.normalize_write_chunk_size(512), 244)

    def test_timeline_redacts_credentials_and_raw(self):
        scalar, redacted = module.sanitize_timeline_scalar(12, "DT_VALUE", 7)
        self.assertIsNone(scalar)
        self.assertTrue(redacted)
        scalar, redacted = module.sanitize_timeline_scalar(47, "DT_BOOL", True)
        self.assertIs(scalar, True)
        self.assertFalse(redacted)
        scalar, redacted = module.sanitize_timeline_scalar(20, "DT_RAW", b"abc")
        self.assertIsNone(scalar)
        self.assertTrue(redacted)

    def test_timeline_bound(self):
        buffer = []
        for i in range(module.EVENT_TIMELINE_CAPACITY + 5):
            module.append_bounded_event(buffer, {"i": i})
        self.assertEqual(len(buffer), module.EVENT_TIMELINE_CAPACITY)
        self.assertEqual(buffer[0]["i"], 5)

    def test_marker_text_is_bounded(self):
        self.assertEqual(module.sanitize_marker_text("  hello   world  ", 64), "hello world")
        self.assertEqual(len(module.sanitize_marker_text("x" * 100, 64)), 64)


if __name__ == "__main__":
    unittest.main()
