"""book-14 T9：取消前归属校验单测（纯文件系统，Windows 可跑）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from h3 import queue_probe as _qp


class TestOwnership(unittest.TestCase):
    def _make_root(self):
        d = Path(tempfile.mkdtemp(prefix="own_"))
        job_dir = d / "workflows" / "h3_20260905_000000_001"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps({
            "prompt_id": "11111111-2222-3333-4444-555555555555"}), encoding="utf-8")
        (d / "last_job.json").write_text(json.dumps({
            "prompt_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}), encoding="utf-8")
        return d

    def test_project_task_found(self):
        old = _qp.ROOT
        _qp.ROOT = self._make_root()
        try:
            self.assertIn("本项目任务", _qp.find_owned("11111111-2222-3333-4444-555555555555"))
            self.assertIn("last_job", _qp.find_owned("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
            self.assertEqual("", _qp.find_owned("99999999-0000-0000-0000-000000000000"))
            self.assertEqual("", _qp.find_owned(""))
        finally:
            _qp.ROOT = old

    def test_unknown_refused(self):
        old = _qp.ROOT
        _qp.ROOT = self._make_root()
        try:
            res = _qp.cancel_owned_task("not-mine-pid")
            self.assertFalse(res["ok"])
            self.assertIn("被拒", res["msg"])
        finally:
            _qp.ROOT = old


if __name__ == "__main__":
    unittest.main()