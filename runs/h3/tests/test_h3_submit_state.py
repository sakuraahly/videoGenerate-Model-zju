"""
h3_submit 断点保留开关回归测试：
成功后是否清断点由 H3_KEEP_BREAKPOINT 决定（编排层注入=保留；CLI/agent 直跑=清除）。
实测教训：直跑成功残留断点会把下一次新任务劫持成旧任务续传并返回旧产物。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from h3_submit import _keep_breakpoint  # noqa: E402


class TestKeepBreakpointFlag(unittest.TestCase):
    def _set(self, val):
        if val is None:
            os.environ.pop("H3_KEEP_BREAKPOINT", None)
        else:
            os.environ["H3_KEEP_BREAKPOINT"] = val

    def test_default_is_clear(self):
        self._set(None)
        self.assertFalse(_keep_breakpoint(), "未注入开关时应清断点（直跑语义）")

    def test_ps_injects_keep(self):
        for v in ("1", "true", "TRUE", "yes"):
            self._set(v)
            self.assertTrue(_keep_breakpoint(), f"编排层注入 {v} 应保留断点")

    def test_falsy_clears(self):
        for v in ("0", "false", "no", ""):
            self._set(v)
            self.assertFalse(_keep_breakpoint(), f"{v} 应按清除处理")

    def tearDown(self):  # noqa: N802
        self._set(None)


if __name__ == "__main__":
    unittest.main()
