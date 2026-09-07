"""S13 成品链封装单测：--finalize 组合开关解析 + 提交参数生效（纯函数/argparse 级）。"""
import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))
from h3_submit import build_arg_parser, apply_finalize  # noqa: E402


def _args(argv):
    return build_arg_parser().parse_args(argv)


class TestFinalizeSwitch(unittest.TestCase):
    def test_finalize_sets_cosy_and_asr(self):
        a = _args(['--stage', 't2v', '--tts-text', '你好', '--finalize'])
        apply_finalize(a)
        self.assertEqual(a.tts_backend, 'cosy')  # 2026-09-07: 默认 CosyVoice2 自然音色
        self.assertTrue(a.asr_check)

    def test_no_finalize_default_cosy(self):
        a = _args(['--stage', 't2v', '--tts-text', '你好'])
        apply_finalize(a)
        self.assertEqual(a.tts_backend, 'cosy')  # 2026-09-07: CosyVoice2 自然音色为默认
        self.assertFalse(a.asr_check)

    def test_explicit_edge_kept(self):
        a = _args(['--stage', 't2v', '--tts-text', '你好', '--tts-backend', 'edge'])
        apply_finalize(a)
        self.assertEqual(a.tts_backend, 'edge')

    def test_finalize_coexists_with_mix_bed(self):
        a = _args(['--stage', 'r2v', '--finalize',
                   '--tts-mix-bed', '/tmp/bed.mp3', '--videos', 'a.mp4'])
        apply_finalize(a)
        self.assertEqual(a.tts_backend, 'cosy')
        self.assertEqual(a.tts_mix_bed, '/tmp/bed.mp3')


if __name__ == '__main__':
    unittest.main()
