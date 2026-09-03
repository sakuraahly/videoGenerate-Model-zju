"""
refimage 素材池逻辑单测：三池扫描 / 选择解析 / promote 复制（纯本地，不碰真库）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# 其它测试模块把全局 tempfile.tempdir 指到 .test_tmp 且在其 teardown 中删除；
# 本模块（字母序最后）重置为系统临时目录，避免 TemporaryDirectory 建目录失败。
tempfile.tempdir = None

from h3 import refimage  # noqa: E402


class TestRows(unittest.TestCase):
    def setUp(self):  # noqa: N802
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self.dirs = {
            "comfy": str(self.base / "comfy"),
            "input": str(self.base / "comfy" / "input"),
            "output": str(self.base / "comfy" / "output"),
            "uploads": str(self.base / "uploads"),
        }
        (self.base / "comfy" / "input").mkdir(parents=True)
        (self.base / "comfy" / "output" / "sub").mkdir(parents=True)
        (self.base / "uploads").mkdir(parents=True)

    def tearDown(self):  # noqa: N802
        self._td.cleanup()

    def test_three_pools_scanned(self):
        (Path(self.dirs["input"]) / "in_a.png").write_bytes(b"1")
        (Path(self.dirs["output"]) / "saved.png").write_bytes(b"2")
        (Path(self.dirs["output"]) / "sub" / "nested.jpg").write_bytes(b"3")
        (Path(self.dirs["uploads"]) / "up_vid.mp4").write_bytes(b"4")
        rows = refimage._rows(self.dirs)
        names = {(r["pool"], r["name"]) for r in rows}
        self.assertIn(("in", "in_a.png"), names)
        self.assertIn(("out", "saved.png"), names)
        self.assertIn(("out", "nested.jpg"), names)   # output 递归
        self.assertIn(("up", "up_vid.mp4"), names)

    def test_kinds(self):
        (Path(self.dirs["input"]) / "a.png").write_bytes(b"1")
        (Path(self.dirs["input"]) / "v.mp4").write_bytes(b"2")
        (Path(self.dirs["input"]) / "notes.txt").write_bytes(b"3")
        rows = refimage._rows(self.dirs)
        kinds = {r["name"]: r["kind"] for r in rows}
        self.assertEqual(kinds["a.png"], "image")
        self.assertEqual(kinds["v.mp4"], "video")
        self.assertEqual(kinds["notes.txt"], "other")

    def test_resolve_sel(self):
        (Path(self.dirs["input"]) / "b.png").write_bytes(b"1")
        rows = refimage._rows(self.dirs)
        r = refimage._resolve_sel(rows, "in:0")
        self.assertEqual(r["name"], "b.png")
        r2 = refimage._resolve_sel(rows, "b.png")
        self.assertEqual(r2["full"], r["full"])
        with self.assertRaises(ValueError):
            refimage._resolve_sel(rows, "out:99")
        with self.assertRaises(ValueError):
            refimage._resolve_sel(rows, "no_such_file_zz.png")

    def test_promote_copies_to_input(self):
        (Path(self.dirs["output"]) / "art.png").write_bytes(b"img")
        rows = refimage._rows(self.dirs)
        rc = refimage.cmd_promote(self.dirs, "out:0")
        self.assertEqual(rc, 0)
        dst = Path(self.dirs["input"]) / "art.png"
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_bytes(), b"img")
        # 已在 input 中：幂等
        self.assertEqual(refimage.cmd_promote(self.dirs, "out:0"), 0)

    def test_promote_unknown_sel(self):
        rows = refimage._rows(self.dirs)
        with self.assertRaises(ValueError):
            refimage._resolve_sel(rows, "nope.png")


class TestTemplateSlots(unittest.TestCase):
    """真实 r2v 镜像模板的槽位结构（只读；模板扩为 8 槽 0/1 激活、其余禁用占位）。"""

    def test_real_r2v_template_slots(self):
        tpl = refimage._stage_template("r2v")
        self.assertTrue(tpl.exists())
        slots = refimage.template_slots(tpl)
        self.assertGreaterEqual(len(slots), 8, "模板至少 8 个参考槽位")
        for entry in slots:
            self.assertEqual(len(entry), 4, "槽位记录=(idx, 图名, 启用, 节点id)")
        self.assertTrue(all(enabled for _i, _n, enabled, _id in slots[:2]),
                        "前两个槽位应处于启用状态")
        # 2..7 为禁用占位（mode=4）
        if len(slots) > 2:
            self.assertTrue(not any(enabled for _i, _n, enabled, _id in slots[2:8]),
                            "2..7 槽位应为禁用占位")
        # 槽位序号连续
        self.assertEqual([s[0] for s in slots], list(range(len(slots))))

    def test_owner_rows_finds_ref_images(self):
        tpl = refimage._stage_template("r2v")
        data = json.loads(tpl.read_text(encoding="utf-8-sig"))
        tgt, rows = refimage._owner_rows(data, "MiniMaxH3ReferenceToVideo",
                                         "ref_images.ref_image_")
        self.assertIsNotNone(tgt)
        self.assertGreaterEqual(len(rows), 8)


if __name__ == "__main__":
    unittest.main()
