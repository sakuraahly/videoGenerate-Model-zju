"""workflow_registry 单测（book-12 步骤1）：解析/禁用/模板健康/validate_all。"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# 本模块只用真实项目资源（模板/注册表），不写临时目录；
# 且不修改全局 tempfile.tempdir（其它模块用 .test_tmp 并在 teardown 删除，
# 若这里再设置会造成 test_refimage 系列临时目录失效）。
from h3 import workflow_registry as wr  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent.parent.parent  # 项目根（tests -> runs*2）

def _entry(**over):
    base = {
        "id": "video_test", "engine": "local", "stage": "test", "enabled": True,
        "template": "workflows/remote_workflows/video_minimax_h3_t2v.json",
        "slots": {"images": [], "videos": [], "audios": []},
        "prompt_inject": {"node_type": "4c314f31-ecda-4b08-ae98-faaba1bf613f", "widget_index": 0},
        "params": {"resolutions": ["360p"], "seconds": {"min": 5, "max": 15}},
        "features": {"reference_videos": False, "per_segment": False, "audio": False,
                     "negative_support": True},
    }
    base.update(over)
    return base


class TestRegistry(unittest.TestCase):
    def test_real_registry_basics(self):
        cap = wr.load_registry(_REPO)
        self.assertGreaterEqual(len(wr.local_entries(cap)), 4)
        self.assertIn("t2v", wr.enabled_stages(cap))

    def test_resolve_stage_and_id(self):
        cap = {"workflows": [_entry()]}
        e, m = wr.resolve(cap, "test")
        self.assertIsNotNone(e)
        self.assertEqual(m, "")
        e2, _ = wr.resolve(cap, "video_test")
        self.assertEqual(e2["stage"], "test")

    def test_resolve_unknown_and_cloud(self):
        cap = {"workflows": [_entry(), {"id": "api_x", "engine": "comfy-cloud"}]}
        e, m = wr.resolve(cap, "bogus")
        self.assertIsNone(e)
        self.assertIn("未知工作流", m)
        e2, m2 = wr.resolve(cap, "api_x")
        self.assertIsNone(e2)
        self.assertIn("未知工作流", m2)

    def test_resolve_disabled(self):
        cap = {"workflows": [_entry(enabled=False)]}
        e, m = wr.resolve(cap, "test")
        self.assertIsNone(e)
        self.assertIn("已禁用", m)

    def test_template_health_ok_on_real_t2v(self):
        cap = {"workflows": [_entry()]}
        e, _ = wr.resolve(cap, "test")
        ok, issues = wr.template_health(_REPO, e)
        self.assertTrue(ok, issues)

    def test_template_health_missing_template(self):
        e = _entry(template="workflows/nonexistent_test.json")
        ok, issues = wr.template_health(_REPO, e)
        self.assertFalse(ok)
        self.assertTrue(any("模板缺失" in i for i in issues))

    def test_template_health_wrong_inject(self):
        e = _entry(prompt_inject={"node_type": "NoSuchNode123", "widget_index": 0})
        ok, issues = wr.template_health(_REPO, e)
        self.assertFalse(ok)
        self.assertTrue(any("注入节点" in i for i in issues))

    def test_template_health_slot_count_shortfall(self):
        # r2v 需要 8 个 LoadImage；用 t2v 模板断言（0 张）配 i2v 规格 → 槽位不足
        e = _entry(id="video_i2v", stage="i2v",
                   template="workflows/remote_workflows/video_minimax_h3_t2v.json",
                   slots={"images": [{"role": "first_frame", "count": 1}]})
        ok, issues = wr.template_health(_REPO, e)
        self.assertFalse(ok)
        self.assertTrue(any("槽位不足" in i for i in issues))

    def test_validate_all_real(self):
        res = wr.validate_all(_REPO)
        ids = [r[0] for r in res]
        self.assertIn("video_t2v", ids)
        all_ok = all(ok for _, ok, _ in res)
        self.assertTrue(all_ok, [r for r in res if not r[1]])

    def test_digest_contains_features(self):
        cap = {"workflows": [_entry(features={"audio": True, "per_segment": True,
                                              "reference_videos": False,
                                              "negative_support": True})]}
        d = wr.digest_entries(cap)
        self.assertIn("features=audio,per_segment,negative_support", d)
        self.assertIn("stage=test", d)


class TestOps(unittest.TestCase):
    """A5：set_enabled/add_local/swap_template（临时 caps 文件，不动真注册表）。"""

    def _caps(self):
        import tempfile
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        cfg_dir = Path(td.name) / "config"
        cfg_dir.mkdir()
        cap_path = cfg_dir / "capabilities.json"
        cap_path.write_text(json.dumps({"workflows": [_entry()]}), encoding="utf-8")
        return cap_path

    def test_set_enabled(self):
        p = self._caps()
        ok, m = wr.set_enabled(p, "test", False)
        self.assertTrue(ok)
        cap = json.loads(p.read_text(encoding="utf-8-sig"))
        self.assertFalse(cap["workflows"][0]["enabled"])
        ok2, m2 = wr.set_enabled(p, "video_test", True)
        self.assertTrue(ok2)
        cap = json.loads(p.read_text(encoding="utf-8-sig"))
        self.assertTrue(cap["workflows"][0]["enabled"])

    def test_add_local(self):
        p = self._caps()
        ok, m = wr.add_local(p, "video_new", "workflows/remote_workflows/video_minimax_h3_t2v.json")
        self.assertTrue(ok)
        cap = json.loads(p.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(cap["workflows"]), 2)
        self.assertEqual(cap["workflows"][1]["stage"], "video_new")
        ok2, _ = wr.add_local(p, "video_new", "x.json")
        self.assertFalse(ok2)

    def test_swap_template_records_sha(self):
        p = self._caps()
        ok, m = wr.swap_template(p, "test", "workflows/new.json")
        self.assertTrue(ok)
        cap = json.loads(p.read_text(encoding="utf-8-sig"))
        self.assertEqual(cap["workflows"][0]["template"], "workflows/new.json")
        self.assertEqual(len(cap["workflows"][0].get("template_sha_history") or []), 1)
        self.assertIn("from", cap["workflows"][0]["template_sha_history"][0])


if __name__ == "__main__":
    unittest.main()
