"""book-19 S10 单测：quality 记录字段/读写/report 汇总（纯函数；compare 需 ffmpeg 仅 spark 用）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from h3.quality import record_fields, load, report, append  # noqa: E402


class TestQuality(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)
        import h3.quality as q
        self._orig = q._log_path
        q._log_path = lambda project_dir=None: self.d / "quality.jsonl"

    def tearDown(self):
        import h3.quality as q
        q._log_path = self._orig
        self._td.cleanup()

    def test_record_fields_mapping(self):
        av = {"width": 1216, "height": 704, "fps": "24/1", "frames": 124,
              "video_duration": 5.166, "audio_codec": "aac", "audio_channels": 2,
              "audio_duration": 5.167, "duration": 5.167, "size": 857840}
        f = record_fields(av)
        self.assertEqual(f["width"], 1216)
        self.assertEqual(f["audio_codec"], "aac")
        self.assertEqual(f["size"], 857840)
        self.assertEqual(f["source"], "probe_av")

    def test_append_write_and_load(self):
        import h3.quality as q
        rec = q.append("out/x.mp4", prompt_id="pid-1", av={
            "width": 608, "height": 352, "fps": "24/1", "frames": 124,
            "video_duration": 5.166, "audio_codec": None, "audio_channels": None,
            "audio_duration": None, "duration": 5.166, "size": 1000})
        rows = load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt_id"], "pid-1")
        self.assertEqual(rows[0]["path"], "x.mp4")

    def test_report_summary(self):
        import h3.quality as q
        q.append("a.mp4", av={"width": 1, "height": 1, "fps": "", "frames": 0,
                              "video_duration": 0, "audio_codec": "aac",
                              "audio_channels": 2, "audio_duration": 0,
                              "duration": 0, "size": 1})
        q.append("b.mp4", av={"width": 1, "height": 1, "fps": "", "frames": 0,
                              "video_duration": 0, "audio_codec": None,
                              "audio_channels": None, "audio_duration": None,
                              "duration": 0, "size": 2})
        d = report()
        self.assertEqual(d["total"], 2)
        self.assertEqual(d["audio_missing_count"], 1)
        self.assertEqual(len(d["recent"]), 2)


if __name__ == '__main__':
    unittest.main()
