"""prompts.inject_local_prompts 注册表 spec 驱动单测（book-12 A1）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from h3 import prompts  # noqa: E402
from h3 import workflow_registry as wr  # noqa: E402

SPEC = {"class_prefix": "MiniMaxH3", "positive_key": "prompt", "negative_key": "negative_prompt"}


def _api_wf():
    return {
        "138": {"class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "TEMPLATE TEXT"}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {"clip": ["128", 0], "prompt": ["138", 0],
                           "negative_prompt": "old negative", "width": 1280}},
        "t1": {"class_type": "TextEncode", "inputs": {"prompt": "scene text"}},
    }


class TestInjectBySpec(unittest.TestCase):
    def test_spec_writes_direct_and_spares_others(self):
        wf = _api_wf()
        n = prompts.inject_local_prompts(wf, "NEW PROMPT", "NEW NEG", spec=SPEC)
        self.assertEqual(n, 2)
        self.assertEqual(wf["136"]["inputs"]["prompt"], "NEW PROMPT")
        self.assertEqual(wf["136"]["inputs"]["negative_prompt"], "NEW NEG")
        self.assertEqual(wf["138"]["inputs"]["value"], "TEMPLATE TEXT")   # 上游不动
        self.assertEqual(wf["t1"]["inputs"]["prompt"], "scene text")      # 其它节点不动

    def test_spec_missing_negative_key_ok(self):
        wf = _api_wf()
        del wf["136"]["inputs"]["negative_prompt"]
        n = prompts.inject_local_prompts(wf, "P", "N", spec=SPEC)
        self.assertEqual(n, 1)
        self.assertEqual(wf["136"]["inputs"]["prompt"], "P")

    def test_spec_miss_falls_back_to_heuristic(self):
        wf = _api_wf()
        spec = {"class_prefix": "NoSuchNode", "positive_key": "prompt",
                "negative_key": "negative_prompt"}
        n = prompts.inject_local_prompts(wf, "P2", "", spec=spec)
        self.assertGreaterEqual(n, 1)   # TextEncode 启发式命中
        self.assertEqual(wf["t1"]["inputs"]["prompt"], "P2")

    def test_no_spec_heuristic_upstream(self):
        wf = _api_wf()
        n = prompts.inject_local_prompts(wf, "P3", "")
        self.assertGreaterEqual(n, 1)
        self.assertEqual(wf["138"]["inputs"]["value"], "P3")   # 启发式改上游

    def test_registry_inject_spec_from_real_entry(self):
        cap = wr.load_registry(Path(__file__).resolve().parent.parent.parent.parent)
        entry, _ = wr.resolve(cap, "r2v")
        spec = wr.inject_spec(entry)
        self.assertEqual(spec.get("class_prefix"), "MiniMaxH3")
        wf = _api_wf()
        prompts.inject_local_prompts(wf, "P4", "", spec=spec)
        self.assertEqual(wf["136"]["inputs"]["prompt"], "P4")


if __name__ == "__main__":
    unittest.main()
