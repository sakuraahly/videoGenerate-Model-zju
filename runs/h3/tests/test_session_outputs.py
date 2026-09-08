"""
session_outputs 会话产物协议单测（planbook §15d）：目录协议/放置/修剪/列表/环境读取（纯本地）。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# 其它测试模块可能把全局 tempfile.tempdir 指到 .test_tmp；这里重置避免互相干扰
tempfile.tempdir = None

from h3 import session_outputs as so  # noqa: E402


class TestDirProtocol(unittest.TestCase):
    def setUp(self):  # noqa: N802
        self._td = tempfile.TemporaryDirectory()
        self.repo = Path(self._td.name)

    def tearDown(self):  # noqa: N802
        self._td.cleanup()

    def test_empty_cid_no_dir(self):
        self.assertIsNone(so.session_out_dir(self.repo, ''))
        self.assertIsNone(so.session_out_dir(self.repo, '   '))
        self.assertIsNone(so.place_output(self.repo, '', Path('x.mp4')))

    def test_dir_layout(self):
        d = so.session_out_dir(self.repo, 'cid_1')
        self.assertEqual(d, self.repo / 'logs' / 'agent_chats' / 'cid_1' / 'outputs')

    def test_place_and_list(self):
        src = self.repo / 'src.mp4'
        src.write_bytes(b'v' * 64)
        dst = so.place_output(self.repo, 'cid_1', src, name='a.mp4')
        self.assertIsNotNone(dst)
        self.assertTrue(dst.is_file())
        self.assertEqual([p.name for p in so.session_videos(self.repo, 'cid_1')], ['a.mp4'])
        self.assertEqual([p.name for p in so.session_files(self.repo, 'cid_1')], ['a.mp4'])

    def test_non_video_skipped_in_videos(self):
        so_dir = so.session_out_dir(self.repo, 'cid_2')
        assert so_dir is not None
        so_dir.mkdir(parents=True)
        (so_dir / 'a.srt').write_text('x', encoding='utf-8')
        src = self.repo / 's.mp4'
        src.write_bytes(b'v' * 16)
        so.place_output(self.repo, 'cid_2', src, name='b.mp4')
        self.assertEqual(len(so.session_videos(self.repo, 'cid_2')), 1)
        self.assertEqual(len(so.session_files(self.repo, 'cid_2')), 2)

    def test_prune_keeps_newest_ten(self):
        src = self.repo / 'src.mp4'
        src.write_bytes(b'v' * 16)
        t = 1_700_000_000.0
        for i in range(12):
            dst = so.place_output(self.repo, 'cid_1', src, name='v%02d.mp4' % i, keep=10)
            if dst is None:
                self.fail('place_output returned None for valid cid')
            t += 1.0
            os.utime(dst, (t, t))  # 显式递增 mtime（避免同秒并列导致顺序不定）
        vids = so.session_videos(self.repo, 'cid_1')
        names = [p.name for p in vids]
        self.assertEqual(len(vids), 10)
        self.assertEqual(vids[0].name, 'v11.mp4')  # 最新在前
        self.assertNotIn('v00.mp4', names)
        self.assertNotIn('v01.mp4', names)
        self.assertIn('v02.mp4', names)

    def test_current_cid_env(self):
        old = os.environ.get(so.ENV_CID)
        os.environ[so.ENV_CID] = '  cidX  '
        try:
            self.assertEqual(so.current_cid(), 'cidX')
        finally:
            if old is None:
                os.environ.pop(so.ENV_CID, None)
            else:
                os.environ[so.ENV_CID] = old


if __name__ == '__main__':
    unittest.main()
