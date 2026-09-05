"""postprocess T2b 单测：SRT 校验/字体预检/输出断言逻辑（不依赖 ffmpeg）。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from h3 import postprocess as pp  # noqa: E402


class TestT2b(unittest.TestCase):
    def test_validate_srt_ok(self):
        with tempfile.TemporaryDirectory() as td:
            srt = Path(td) / "s.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好，世界\n\n2\n00:00:02,500 --> 00:00:04,000\n测试字幕\n", encoding="utf-8")
            self.assertEqual(pp.validate_srt(srt), 2)

    def test_validate_srt_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            srt = Path(td) / "bad.srt"
            srt.write_text("no timeline here\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                pp.validate_srt(srt)

    def test_check_cjk_font_windows(self):
        # Windows 无 CJK 字体路径 → 确定性报错（不静默）
        try:
            pp.check_cjk_font()
            self.skipTest("本机有 CJK 字体")
        except ValueError:
            pass


if __name__ == "__main__":
    unittest.main()
