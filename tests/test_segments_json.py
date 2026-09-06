"""book-19 S4 单测：槽名对齐 / blueprints 键 / 0-based JSON / 段数守卫（纯函数，Windows 可跑）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/
from h3.idea2prompts import _is_flf2v_slot, _blueprint_slot, _segments_dict_0based  # noqa: E402


class TestSlotAlignment(unittest.TestCase):
    def test_flf2v_variants(self):
        for s in ('flf2v', 'video_flf2v', 'api_flf2v'):
            self.assertTrue(_is_flf2v_slot(s))

    def test_non_flf2v(self):
        for s in ('video_r2v', 'default', 'video_t2v'):
            self.assertFalse(_is_flf2v_slot(s))

    def test_blueprint_key(self):
        self.assertEqual(_blueprint_slot('flf2v'), 'video_flf2v')
        self.assertEqual(_blueprint_slot('video_flf2v'), 'video_flf2v')
        self.assertEqual(_blueprint_slot('video_r2v'), 'video_r2v')


class TestSegmentsDict(unittest.TestCase):
    def test_0based_keys(self):
        segs = [{'positive': 'A', 'negative': 'n1'},
                {'positive': 'B', 'negative': 'n2'},
                {'positive': 'C', 'negative': 'n3'}]
        d = _segments_dict_0based(segs)
        self.assertEqual(d, {'0': 'A', '1': 'B', '2': 'C'})
        self.assertNotIn('3', d)  # 0-based 与 batch 对齐（1-based 旧口径已废弃）

    def test_missing_positive_defaults_empty(self):
        d = _segments_dict_0based([{'negative': 'x'}, {'positive': 'B'}])
        self.assertEqual(d, {'0': '', '1': 'B'})


if __name__ == '__main__':
    unittest.main()
