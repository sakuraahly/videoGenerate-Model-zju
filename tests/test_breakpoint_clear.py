"""book-19 §12 单测：任务完成自动清断点（clear_breakpoint_on_done，幂等/非目标不清）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from runs.agent import task_watch as _tw  # noqa: E402


class TestClearBreakpoint(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self._orig = _tw._PROJECT_ROOT
        _tw._PROJECT_ROOT = str(self.root)

    def tearDown(self):
        _tw._PROJECT_ROOT = self._orig
        self._td.cleanup()

    def _bp(self, pid):
        p = self.root / "last_job.json"
        p.write_text(json.dumps({"prompt_id": pid}), encoding="utf-8")
        return p

    def test_clears_when_same_pid(self):
        p = self._bp("abc-123")
        _tw.clear_breakpoint_on_done("abc-123")
        self.assertFalse(p.exists())

    def test_keeps_other_pid(self):
        p = self._bp("abc-123")
        _tw.clear_breakpoint_on_done("xyz-999")
        self.assertTrue(p.exists())

    def test_idempotent_no_file(self):
        _tw.clear_breakpoint_on_done("nope")
        self.assertFalse((self.root / "last_job.json").exists())


if __name__ == '__main__':
    unittest.main()
