"""stage.apply_generation_params 单测（book-12 修复：模板默认值≠请求参数）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

from h3 import stage  # noqa: E402


def _wf():
    return {
        "115": {"class_type": "ResolutionSelector",
                "inputs": {"aspect_ratio": "16:9", "megapixels": "0.4", "multiple": "32"}},
        "131": {"class_type": "ComfyMathExpression",
                "inputs": {"values.a": ["132", 0],
                           "expression": "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {"clip": ["128", 0], "vae": ["119", 0],
                           "ref_images.ref_image_0": ["137", 0],
                           "width": ["115", 0], "height": ["115", 1],
                           "length": ["131", 1]}},
        "124": {"class_type": "BasicScheduler", "inputs": {"model": ["127", 0], "steps": 20}},
        "130": {"class_type": "CreateVideo", "inputs": {"fps": 24}},
        "Save": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "x"}},
    }


class TestGenParams(unittest.TestCase):
    def test_override_replaces_template_defaults(self):
        wf = _wf()
        tok = {"width": "1280", "height": "736", "length": "362",
               "steps": "20", "fps": "24"}
        n = stage.apply_generation_params(wf, tok)
        ins = wf["136"]["inputs"]
        self.assertEqual(ins["width"], 1280)
        self.assertEqual(ins["height"], 736)
        self.assertEqual(ins["length"], 362)
        self.assertGreaterEqual(n, 1)

    def test_no_targets_returns_zero(self):
        wf = {"1": {"class_type": "LoadImage", "inputs": {}}}
        self.assertEqual(stage.apply_generation_params(wf, {"width": "1"}), 0)

    def test_steps_and_fps_override(self):
        wf = _wf()
        wf["124"]["inputs"]["steps"] = 10
        wf["130"]["inputs"]["fps"] = 30
        stage.apply_generation_params(wf, {"width": "1", "height": "1",
                                           "length": "1", "steps": "20", "fps": "24"})
        self.assertEqual(wf["124"]["inputs"]["steps"], 20)
        self.assertEqual(wf["130"]["inputs"]["fps"], 24)


class TestApplyLora(unittest.TestCase):
    """book-12 B1：加速 LoRA 注入（LoraLoaderModelOnly + steps 覆写）。"""

    def _wf(self):
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "m.safetensors"}},
            "6": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0]}},
            "8": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "steps": 20}},
            "11": {"class_type": "SamplerCustomAdvanced", "inputs": {"model": ["1", 0]}},
        }

    _LMAP = {"files": {"ref2v_4step": "ref2v_4.safetensors"},
             "steps": {"ref2v_4step": 4}}

    def test_inject_replaces_model_refs_and_steps(self):
        wf = self._wf()
        n = stage.apply_lora(wf, "ref2v_4step", self._LMAP)
        self.assertGreaterEqual(n, 3)
        lora_id = next(k for k, v in wf.items()
                       if isinstance(v, dict) and v.get("class_type") == "LoraLoaderModelOnly")
        self.assertIn("ref2v_4.safetensors", wf[lora_id]["inputs"]["lora_name"])
        self.assertEqual(wf[lora_id]["inputs"]["model"], ["1", 0])
        self.assertEqual(wf["6"]["inputs"]["model"], [lora_id, 0])
        self.assertEqual(wf["8"]["inputs"]["steps"], 4)
        self.assertEqual(wf["11"]["inputs"]["model"], [lora_id, 0])

    def test_none_or_unknown_returns_zero(self):
        wf = self._wf()
        self.assertEqual(stage.apply_lora(wf, "none", self._LMAP), 0)
        self.assertEqual(stage.apply_lora(wf, "bogus", self._LMAP), 0)
        self.assertEqual(stage.apply_lora(wf, "ref2v_4step", {}), 0)
        wf2 = {"1": {"class_type": "LoadImage"}}
        self.assertEqual(stage.apply_lora(wf2, "ref2v_4step", self._LMAP), 0)


if __name__ == "__main__":
    unittest.main()
