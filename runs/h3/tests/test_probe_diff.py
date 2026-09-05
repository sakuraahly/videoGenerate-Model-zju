"""h3_submit._probe_diff 单测（book-12 B2/T3 产物参数对冲）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from h3_submit import _probe_diff  # noqa: E402

OK = "width=1280\nheight=736\nr_frame_rate=24/1\nnb_frames=362\nduration=15.083333\n"
DIFF_RES = OK.replace("width=1280", "width=864").replace("height=736", "height=480")
DIFF_FRAME = OK.replace("nb_frames=362", "nb_frames=124")
DIFF_DUR = OK.replace("duration=15.083333", "duration=5.166667")


class TestProbeDiff(unittest.TestCase):
    def test_match_empty(self):
        self.assertEqual(_probe_diff(OK, 1280, 736, 362, 15), "")

    def test_resolution_mismatch(self):
        self.assertIn("分辨率", _probe_diff(DIFF_RES, 1280, 736, 362, 15))

    def test_frame_mismatch(self):
        self.assertIn("帧数", _probe_diff(DIFF_FRAME, 1280, 736, 362, 15))

    def test_duration_mismatch(self):
        self.assertIn("时长", _probe_diff(DIFF_DUR, 1280, 736, 362, 15))

    def test_empty_input_ok(self):
        self.assertEqual(_probe_diff("", 0, 0, 0, 0), "")


if __name__ == "__main__":
    unittest.main()
