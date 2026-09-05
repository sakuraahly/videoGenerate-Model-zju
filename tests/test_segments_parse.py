"""book-13 P1#5：分段 JSON 解析单测。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from h3.idea2prompts import parse_segments_json  # noqa: E402


class TestSegmentsParse(unittest.TestCase):
    def test_valid(self):
        raw = ('{"segments": [{"positive": "P1", "negative": "N1"}, {"positive": "P2"}]}')
        segs = parse_segments_json(raw)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["positive"], "P1")
        self.assertEqual(segs[1]["negative"], "")

    def test_fenced(self):
        raw = ('```json\n{"segments": [{"positive": "A"}]}\n```')
        segs = parse_segments_json(raw)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["positive"], "A")

    def test_invalid_fallback(self):
        segs = parse_segments_json("普通文本输出")
        self.assertEqual(len(segs), 1)
        self.assertIn("普通文本", segs[0]["positive"])

    def test_empty_segments_fallback(self):
        segs = parse_segments_json('{"segments": []}')
        self.assertEqual(len(segs), 1)


if __name__ == "__main__":
    unittest.main()