"""book-19 §10 P1.5 参考语义修复单测：tag 契约解析/校验 + ref_image_size 参数化。

纯函数、无网络（Windows 可跑）。覆盖落点：
- h3.prompts: reference_tag_set / missing_reference_tags / has_ref_persist_sentence
  / ref_tag_contract_rule / _ref_contract_violation（idea2prompts 校验）
- h3.stage: apply_ref_image_size / count_wired_reference_images
- h3.params: ref_image_size 默认 max + 枚举校验
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))  # runs/

from h3 import params as h3params  # noqa: E402
from h3 import prompts as h3prompts  # noqa: E402
from h3 import stage as h3stage  # noqa: E402

PERSIST_SENTENCE = ("The reference images (scene/character/props) are locked "
                    "throughout the whole shot; they are NOT first-frame/last-frame "
                    "keyframes; keep every frame consistent.")


class TestRefTagNormalize(unittest.TestCase):
    """2026-09-10：0 基编号归一化（用户/AI 常写 <Picture 0> 起）。"""

    def test_zero_based_shifted(self):
        p = ("<Picture 0> is the room. <Picture 1> is Sharon. "
             "<Picture 2> is the father. <picture 3> is the glasses.")
        out = h3prompts.normalize_picture_tags(p)
        self.assertEqual(h3prompts.reference_tag_set(out), {1, 2, 3, 4})
        self.assertIn('<Picture 4>', out)
        self.assertNotIn('<Picture 0>', out)

    def test_one_based_untouched(self):
        p = "<Picture 1> a <Picture 2> b"
        self.assertEqual(h3prompts.normalize_picture_tags(p), p)

    def test_zero_with_one_also_shifted(self):
        # 用户实际写法（0 起且含 1）：必须整体平移，否则契约仍会拒
        p = "<Picture 0> room, <Picture 1> Sharon, <Picture 2> father"
        out = h3prompts.normalize_picture_tags(p)
        self.assertEqual(h3prompts.reference_tag_set(out), {1, 2, 3})

    def test_no_tags_untouched(self):
        p = "no tags here"
        self.assertEqual(h3prompts.normalize_picture_tags(p), p)


class TestRefTagParse(unittest.TestCase):
    def test_tag_extraction(self):
        p = "Use <Picture 1> for the character and <Picture 2> for the scene. Also <picture 3> and <Picture  4 >."
        self.assertEqual(h3prompts.reference_tag_set(p), {1, 2, 3, 4})

    def test_no_tags(self):
        self.assertEqual(h3prompts.reference_tag_set("no tags here"), set())

    def test_missing_none(self):
        p = "locked <Picture 1> and <Picture 2> throughout the whole shot"
        self.assertEqual(h3prompts.missing_reference_tags(p, 2), [])

    def test_missing_gap(self):
        p = "only <Picture 1>, forgot the second"
        self.assertEqual(h3prompts.missing_reference_tags(p, 2), [2])
        self.assertEqual(h3prompts.missing_reference_tags(p, 3), [2, 3])

    def test_zero_refs(self):
        self.assertEqual(h3prompts.missing_reference_tags("anything", 0), [])

    def test_persist_sentence(self):
        self.assertTrue(h3prompts.has_ref_persist_sentence(PERSIST_SENTENCE))
        self.assertFalse(h3prompts.has_ref_persist_sentence("a shot of the living room"))

    def test_contract_rule_scope(self):
        self.assertIn("<Picture 1>", h3prompts.ref_tag_contract_rule("video_r2v"))
        self.assertIn("<Picture 1>", h3prompts.ref_tag_contract_rule("api_r2v"))
        self.assertEqual(h3prompts.ref_tag_contract_rule("video_t2v"), "")
        self.assertEqual(h3prompts.ref_tag_contract_rule("default"), "")


class TestIdea2PromptsViolation(unittest.TestCase):
    def _viol(self, positive: str, slot: str) -> str:
        from h3.idea2prompts import _ref_contract_violation
        return _ref_contract_violation(positive, slot)

    def test_complete_prompt_ok(self):
        p = f"<Picture 1> and <Picture 2> references. {PERSIST_SENTENCE}"
        self.assertEqual(self._viol(p, "video_r2v"), "")

    def test_missing_tags(self):
        self.assertIn("Picture", self._viol("a nice shot, no tags", "video_r2v"))

    def test_missing_persist_sentence(self):
        p = "Use <Picture 1> and <Picture 2>, then action."
        v = self._viol(p, "video_r2v")
        self.assertTrue(v)  # tag 存在但缺贯穿句 → 仍违规
        self.assertIn("语义句", v)

    def test_non_r2v_never_violates(self):
        self.assertEqual(self._viol("anything", "video_t2v"), "")


class TestApplyRefImageSize(unittest.TestCase):
    def _wf(self, ref_size=None, node_type="MiniMaxH3ReferenceToVideo"):
        ins = {"clip": [1, 0], "width": 1344}
        if ref_size is not None:
            ins["ref_image_size"] = ref_size
        return {"136": {"class_type": node_type, "inputs": ins},
                "1": {"class_type": "CLIPLoader", "inputs": {}}}

    def test_overwrite_match_to_max(self):
        wf = self._wf(ref_size="match")
        self.assertEqual(h3stage.apply_ref_image_size(wf, "max"), 1)
        self.assertEqual(wf["136"]["inputs"]["ref_image_size"], "max")

    def test_no_node_no_change(self):
        wf = {"1": {"class_type": "CLIPLoader", "inputs": {}}}
        self.assertEqual(h3stage.apply_ref_image_size(wf, "max"), 0)

    def test_wrong_node_type_no_change(self):
        wf = self._wf(ref_size="match", node_type="MiniMaxH3ImageToVideo")
        # 参考节点专用（RefToVideo）——不误改其它 MiniMaxH3 节点
        self.assertEqual(h3stage.apply_ref_image_size(wf, "max"), 0)

    def test_absent_key_skipped(self):
        wf = self._wf(ref_size=None)
        self.assertEqual(h3stage.apply_ref_image_size(wf, "max"), 0)


class TestCountWiredReferences(unittest.TestCase):
    def test_counts_wired_only(self):
        wf = {"136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "ref_images.ref_image_0": ["137", 0],
            "ref_images.ref_image_1": ["139", 0],
            "ref_images.ref_image_2": None,   # 未接线不计数
            "ref_videos.ref_video_0": None,   # 非图片槽不计数
            "width": 1344,
        }}}
        self.assertEqual(h3stage.count_wired_reference_images(wf), 2)

    def test_no_ref_node(self):
        self.assertEqual(h3stage.count_wired_reference_images({"1": {"class_type": "X", "inputs": {}}}), 0)


class TestRefImageSizeParams(unittest.TestCase):
    def test_default_max(self):
        gp = h3params.resolve_params({}, prompt="p", negative_prompt="")
        self.assertEqual(gp.ref_image_size, "max")

    def test_override_match(self):
        gp = h3params.resolve_params({}, prompt="p", negative_prompt="",
                                     cli_overrides={"ref_image_size": "match"})
        self.assertEqual(gp.ref_image_size, "match")

    def test_invalid_rejected(self):
        with self.assertRaises(h3params.ParamError):
            h3params.resolve_params({}, prompt="p", negative_prompt="",
                                    cli_overrides={"ref_image_size": "huge"})

    def test_workflow_dict_includes(self):
        gp = h3params.resolve_params({}, prompt="p", negative_prompt="")
        self.assertEqual(gp.workflow_dict()["ref_image_size"], "max")


if __name__ == "__main__":
    unittest.main()
