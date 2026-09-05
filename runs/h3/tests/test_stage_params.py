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


if __name__ == "__main__":
    unittest.main()
