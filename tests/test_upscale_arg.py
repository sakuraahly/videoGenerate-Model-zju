"""S13 超分参数单测：--upscale 解析与默认。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))
from h3_submit import build_arg_parser, apply_finalize  # noqa: E402


class TestUpscaleArg(unittest.TestCase):
    def test_default_none(self):
        a = build_arg_parser().parse_args(['--stage', 't2v'])
        self.assertEqual(a.upscale, 'none')

    def test_4x_choice(self):
        a = build_arg_parser().parse_args(['--stage', 't2v', '--upscale', '4x'])
        self.assertEqual(a.upscale, '4x')

    def test_finalize_with_upscale(self):
        a = build_arg_parser().parse_args(['--stage', 'r2v', '--finalize', '--upscale', '4x'])
        apply_finalize(a)
        self.assertEqual(a.tts_backend, 'local')
        self.assertEqual(a.upscale, '4x')


if __name__ == '__main__':
    unittest.main()
