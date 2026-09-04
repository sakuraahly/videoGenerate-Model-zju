"""
logutil 单元测试：统一运行日志模块（runs/h3/logutil.py）。

运行方式（在项目根目录）：
  python -m unittest discover -s runs/h3/tests -p "test_*.py" -v
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

_TEST_TMP = Path(__file__).resolve().parent / ".test_tmp"
_WRITES_OK = True
try:
    _TEST_TMP.mkdir(exist_ok=True)
    tempfile.tempdir = str(_TEST_TMP)
except OSError:
    _WRITES_OK = False

needs_fs = unittest.skipUnless(_WRITES_OK, "沙箱不允许子进程写文件，跳过文件类测试")


def setUpModule():  # noqa: N802
    os.environ.pop("H3_LOG_FILE", None)


def tearDownModule():  # noqa: N802
    os.environ.pop("H3_LOG_FILE", None)
    if _WRITES_OK:
        shutil.rmtree(_TEST_TMP, ignore_errors=True)


from h3 import logutil  # noqa: E402


@needs_fs
class TestLogutilFileCreation(unittest.TestCase):
    def setUp(self):  # noqa: N802
        os.environ.pop("H3_LOG_FILE", None)

    def test_auto_bootstrap_creates_run_log(self):
        with tempfile.TemporaryDirectory() as td:
            path = logutil.ensure_run_log(td, "tool-x")
            self.assertTrue(path)
            p = Path(path)
            self.assertTrue(p.exists())
            head = p.read_text(encoding="utf-8")
            self.assertIn("=== tool-x run start ===", head)

    def test_env_override_reuses_existing(self):
        with tempfile.TemporaryDirectory() as td:
            mine = Path(td) / "shared.log"
            mine.write_text("", encoding="utf-8")
            os.environ["H3_LOG_FILE"] = str(mine)
            try:
                out = logutil.ensure_run_log(td, "tool-y")
                self.assertEqual(out, str(mine))
                self.assertFalse((Path(td) / "logs").exists())
            finally:
                os.environ.pop("H3_LOG_FILE", None)


@needs_fs
class TestLogutilEvents(unittest.TestCase):
    def setUp(self):  # noqa: N802
        os.environ.pop("H3_LOG_FILE", None)

    def _new_file(self, td):
        os.environ.pop("H3_LOG_FILE", None)
        return logutil.ensure_run_log(td, "tool-z")

    def test_log_event_format(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._new_file(td)
            logutil.log_event("tool-z", logutil.fmt(event="task", idea_len=5, dry_run=False))
            logutil.log_start("tool-z", ["--idea", "hi"])
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            self.assertTrue(any("py: tool-z event=task idea_len=5 dry_run=False" in l for l in lines),
                            lines)
            self.assertTrue(any("py: tool-z start argv=['--idea', 'hi']" in l for l in lines),
                            lines)
            self.assertTrue(all(l.startswith("[") and "] py: " in l for l in lines))

    def test_no_crash_when_log_dir_unwritable(self):
        # logs 路径被同名文件占住 → mkdir 失败 → 静默返回空串，不抛异常
        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "logs"
            blocker.write_text("i am a file", encoding="utf-8")
            out = logutil.ensure_run_log(td, "tool-q")
            self.assertEqual(out, "")

    def test_log_file_unified_format(self):
        # book-11：log_file 写指定文件，统一格式 `[ts] py: <tool> <event>`
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sync_auto.log"
            logutil.log_file(str(p), "sync-auto", "合并轮开始……")
            logutil.log_file(str(p), "sync-auto", "合并轮完成。")
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith("[") and "] py: sync-auto " in lines[0])

    def test_log_file_rotate(self):
        # 超过上限（用极小上限触发）→ 旋转到 .1
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "big.log"
            logutil.log_file(str(p), "t", "x" * 2000, rotate_mb=0.001)  # 1KB 上限
            logutil.log_file(str(p), "t", "y" * 2000, rotate_mb=0.001)
            self.assertTrue((Path(str(p) + ".1")).exists())
            self.assertTrue(p.exists())


if __name__ == "__main__":
    unittest.main()
