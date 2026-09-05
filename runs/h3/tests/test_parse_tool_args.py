"""ui_app._parse_tool_args 单测（book-16：JSON/KV/围栏）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from runs.agent.ui_app import _parse_tool_args  # noqa: E402


class TestParseToolArgs(unittest.TestCase):
    def test_json(self):
        self.assertEqual(_parse_tool_args('{"stage": "t2v", "seconds": 5}'),
                         {"stage": "t2v", "seconds": 5})

    def test_kv(self):
        d = _parse_tool_args('stage=t2v, resolution=360p, seconds=5, dry_run=false')
        self.assertEqual(d.get("stage"), "t2v")
        self.assertEqual(d.get("seconds"), 5)
        self.assertIs(d.get("dry_run"), False)

    def test_kv_quoted(self):
        d = _parse_tool_args("theme='love', n=3")
        self.assertEqual(d.get("theme"), "love")

    def test_fence(self):
        txt = chr(96) * 3 + chr(34) * 0 + "json" + chr(10) + '{"a": 1}' + chr(10) + chr(96) * 3
        self.assertEqual(_parse_tool_args(txt), {"a": 1})

    def test_empty(self):
        self.assertEqual(_parse_tool_args(""), {})
        self.assertEqual(_parse_tool_args(None), {})


if __name__ == "__main__":
    unittest.main()