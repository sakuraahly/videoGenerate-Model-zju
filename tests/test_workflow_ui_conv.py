"""新bug：workflow_to_ui 支持字符串节点 id（apply_lora 注入 lora_N）。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from h3.workflow import workflow_to_ui

WITH_LORA = {
    "1": {"class_type": "VAELoader", "inputs": {"vae_name": "a"}},
    "lora_14": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["2", 0], "lora_name": "x", "strength_model": 1.0}},
    "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "u"}},
    "3": {"class_type": "KSampler", "inputs": {"model": ["lora_14", 0]}},
}


class TestUiConv(unittest.TestCase):
    def test_string_ids_convert(self):
        ui = workflow_to_ui(WITH_LORA)
        ids = [n["id"] for n in ui["nodes"]]
        self.assertEqual(len(ids), 4)
        self.assertTrue(all(isinstance(i, int) for i in ids))
        self.assertEqual(len(ui["links"]), 2)
        self.assertGreater(ui["last_node_id"], 0)

    def test_json_loads(self):
        self.assertIn("nodes", json.dumps(workflow_to_ui(WITH_LORA)))


if __name__ == "__main__":
    unittest.main()