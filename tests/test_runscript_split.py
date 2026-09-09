"""book-19 单测：run_script 参数解析（shlex 引号保留——高频坑根因）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根（runs 包从根导入）
from runs.agent.toolcall_parse import _split_args  # noqa: E402


class TestSplitArgs(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(_split_args('--stage t2v --seconds 5'), ['--stage', 't2v', '--seconds', '5'])

    def test_quoted_prompt(self):
        # 2026-09-09 高频坑：模型传 --prompt "A cat at night ..." 被旧 split 拆碎
        out = _split_args('--prompt "A cat at night, cinematic" --seconds 4')
        self.assertEqual(out[1], 'A cat at night, cinematic')
        self.assertEqual(out[0], '--prompt')

    def test_single_quotes_and_unicode(self):
        out = _split_args("--line '路上小心。' --voice yunxi")
        self.assertEqual(out[1], '路上小心。')

    def test_empty(self):
        self.assertEqual(_split_args(''), [])


if __name__ == '__main__':
    unittest.main()
