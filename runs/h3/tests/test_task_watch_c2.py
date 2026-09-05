"""task_watch C2 单元测试（eta_hint/elapsed 逻辑）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# Windows 无 requests：仅测纯逻辑，stub 模块即可（不触碰网络）
import sys as _sys, types as _types  # noqa: E402
if 'requests' not in _sys.modules:
    _sys.modules['requests'] = _types.ModuleType('requests')

from runs.agent import task_watch as tw  # noqa: E402


class TestC2(unittest.TestCase):
    def test_eta_hint_per_status(self):
        self.assertIn("排队中", tw._eta_hint("queued"))
        self.assertIn("H3 单段常规", tw._eta_hint("running"))
        self.assertIn("失败", tw._eta_hint("failed"))
        self.assertEqual(tw._eta_hint("completed"), "")

    def test_elapsed_accumulates(self):
        pid = "c2-test-1"
        e1 = tw._elapsed(pid)
        e2 = tw._elapsed(pid)
        self.assertGreaterEqual(e2, e1)
        self.assertIn(pid, tw._first_seen)


if __name__ == "__main__":
    unittest.main()
