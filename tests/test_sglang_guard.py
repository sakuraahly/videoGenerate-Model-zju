"""book-19 §14 单测：sglang_guard 决策函数（纯函数，Windows 可跑）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from runs.agent.sglang_guard import decide  # noqa: E402


class TestDecide(unittest.TestCase):
    def test_ok_when_ping(self):
        st, _ = decide(True, 40.0)
        self.assertEqual(st, "ok")

    def test_wait_when_comfy_high(self):
        st, msg = decide(False, 40.0, threshold=32.0)
        self.assertEqual(st, "wait")
        self.assertIn("等待", msg)

    def test_wait_when_unknown(self):
        st, _ = decide(False, None)
        self.assertEqual(st, "wait")

    def test_start_when_low(self):
        st, msg = decide(False, 20.0, threshold=32.0)
        self.assertEqual(st, "start")
        self.assertIn("可共存", msg)

    def test_threshold_boundary(self):
        st, _ = decide(False, 32.0, threshold=32.0)
        self.assertEqual(st, "wait")


if __name__ == '__main__':
    unittest.main()
