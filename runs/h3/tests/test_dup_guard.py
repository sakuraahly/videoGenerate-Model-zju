"""ui_app 防复读纯函数单测（book-13 输出异常保护）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# gradio 环境隔离：只测纯函数（模块顶层 import gradio 时这里可能失败——改为加载源码函数）
import ast

src = Path(__file__).resolve().parent.parent.parent / "agent" / "ui_app.py"
tree = ast.parse(src.read_text(encoding="utf-8"))
func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_dup_text")
mod = ast.Module(body=[func], type_ignores=[])
ns = {}
exec(compile(mod, "ui_app._dup_text", "exec"), ns)
_dup_text = ns["_dup_text"]


class TestDupText(unittest.TestCase):
    def test_duplicate_tail(self):
        self.assertTrue(_dup_text("用户要求：不要调用工具", "先讲点话。用户要求：不要调用工具"))
        self.assertTrue(_dup_text("同样的开头内容啊", "同样的开头内容啊"))

    def test_fresh_text(self):
        self.assertFalse(_dup_text("你好呀", "之前的正文"))
        self.assertFalse(_dup_text("", "任何"))


if __name__ == "__main__":
    unittest.main()
