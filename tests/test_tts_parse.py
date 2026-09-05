"""book-14 T2b：SRT 解析纯函数单测（Windows 可跑，不依赖 edge-tts）。"""
import tempfile
import unittest
from pathlib import Path

from runs.h3.tts import parse_srt

SRT = """1
00:00:00,500 --> 00:00:02,000
再见了，故乡。

2
00:00:02,200 --> 00:00:04,500
我会回来的。
"""


class TestTtsParse(unittest.TestCase):
    def test_parse_basic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.srt"
            p.write_text(SRT, encoding="utf-8")
            segs = parse_srt(p)
            self.assertEqual(len(segs), 2)
            s0, e0, t0 = segs[0]
            self.assertAlmostEqual(s0, 0.5, places=2)
            self.assertAlmostEqual(e0, 2.0, places=2)
            self.assertEqual(t0, "再见了，故乡。")
            self.assertAlmostEqual(segs[1][0], 2.2, places=2)

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            parse_srt(Path("Z:/nope.srt"))

    def test_empty_srt(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.srt"
            p.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_srt(p)

    def test_no_time_skip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.srt"
            p.write_text("only text\n无时间轴", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_srt(p)


if __name__ == "__main__":
    unittest.main()