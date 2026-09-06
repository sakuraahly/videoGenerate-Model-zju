"""book-19 S9 单测：sessions list/export/search 纯函数（临时目录，Windows 可跑）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root（dev.py 所在）
from runs.dev import sessions_list, sessions_export, sessions_search  # noqa: E402


def _mk(dirp, cid, msgs):
    with open(dirp / (cid + ".jsonl"), "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


class TestSessions(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)
        _mk(self.d, "cid_a", [{"role": "user", "content": "帮我生成视频"},
                              {"role": "assistant", "content": "好的，参考图生视频"}])
        _mk(self.d, "cid_b", [{"role": "user", "content": "另一个任务：猫"}])

    def tearDown(self):
        self._td.cleanup()

    def test_list(self):
        rows = sessions_list(self.d)
        self.assertEqual(len(rows), 2)
        titles = {cid: t for cid, t in rows}
        self.assertIn("帮我生成视频", titles["cid_a"])
        self.assertIn("另一个任务", titles["cid_b"])

    def test_export(self):
        out = sessions_export(self.d, "cid_a", out_dir=self._td.name + "/out")
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 会话 cid_a", text)
        self.assertIn("帮我生成视频", text)
        self.assertIn("参考图生视频", text)

    def test_export_missing(self):
        with self.assertRaises(FileNotFoundError):
            sessions_export(self.d, "nope", out_dir=self._td.name + "/out2")

    def test_search(self):
        hits = sessions_search(self.d, "猫")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], "cid_b")

    def test_search_cid_filter(self):
        hits = sessions_search(self.d, "视频", cid="cid_a")
        self.assertEqual(len(hits), 2)  # cid_a 的 user+assistant 两行均命中
        self.assertTrue(all(c == "cid_a" for c, _ in hits))
        self.assertTrue(all("视频" in line for _, line in hits))


if __name__ == '__main__':
    unittest.main()
