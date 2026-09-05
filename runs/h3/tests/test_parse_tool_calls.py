"""toolcall_parse 单测（book-16 qwen3.8 native tool-call）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from runs.agent.toolcall_parse import _parse_tool_calls  # noqa: E402


class TestParseToolCalls(unittest.TestCase):
    def test_tag_call(self):
        txt = "我要调用工具。<tool_call> <function=list_references> {}\n</function> </tool_call>"
        calls, clean = _parse_tool_calls(txt)
        self.assertEqual(calls[0][0], "list_references")
        self.assertNotIn("<tool_call>", clean)
        self.assertIn("我要调用工具", clean)

    def test_no_tag(self):
        calls, clean = _parse_tool_calls("你好呀")
        self.assertEqual(calls, [])
        self.assertEqual(clean, "你好呀")


if __name__ == "__main__":
    unittest.main()
