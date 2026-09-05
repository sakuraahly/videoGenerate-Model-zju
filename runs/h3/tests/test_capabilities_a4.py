"""capabilities A4 动态认知单测（digest/compose/registry-doc）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from h3 import capabilities as capmod  # noqa: E402

SYS = ("头部\n"
       "═══ 工作流（只用本地，不提 api_*）═══\n"
       "- t2v：文生视频（文字→视频）\n"
       "- flf2v：首末帧转场\n"
       "\n"
       "后续段")


class TestA4(unittest.TestCase):
    def _digest(self):
        root = Path(__file__).resolve().parent.parent.parent.parent  # 项目根
        d = capmod.agent_digest(root)
        self.assertIn("stage=", d)
        return d

    def test_compose_replaces_block(self):
        d = self._digest()
        out = capmod.compose_system_message(SYS, d)
        self.assertIn("注册表动态声明", out)
        self.assertNotIn("只用本地，不提 api_*", out)
        self.assertIn("后续段", out)  # 段后不变
        self.assertTrue(out.index("注册表动态声明") < out.index("后续段"))

    def test_compose_empty_digest_returns_original(self):
        self.assertEqual(capmod.compose_system_message(SYS, ""), SYS)

    def test_compose_no_marker_appends(self):
        out = capmod.compose_system_message("无块", self._digest())
        self.assertIn("注册表动态声明", out)

    def test_digest_contains_disabled_missing(self):
        import json
        root = Path(__file__).resolve().parent.parent.parent.parent
        cap = json.loads((root / "config" / "capabilities.json").read_text(encoding="utf-8-sig"))
        import copy
        cap2 = copy.deepcopy(cap)
        cap2["workflows"][0]["enabled"] = False
        from h3 import workflow_registry
        d = workflow_registry.digest_entries(cap2)
        first = "video_t2v" in d
        self.assertFalse(first, "禁用工作流不应出现在 digest")

    def test_registry_doc_written(self):
        root = Path(__file__).resolve().parent.parent.parent.parent
        dst = capmod.write_registry_doc(root)
        self.assertTrue(dst.exists())
        txt = dst.read_text(encoding="utf-8")
        self.assertIn("workflows-registry", dst.name)
        self.assertIn("stage=t2v", txt)


if __name__ == "__main__":
    unittest.main()
