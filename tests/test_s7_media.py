"""book-19 S7 单测：参考视频/音频 API 层注入（设计 B）+ 媒体 tag 契约 + 注册表扩展。

纯函数级（无需 ffmpeg/在线 ComfyUI/mock client）：inject_media_refs 的字段/槽位键/守卫、
prompts 媒体 tag 函数、workflow_registry add_local slots/features 与 template_health 分型。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'runs'))
from h3 import stage as h3stage  # noqa: E402
from h3 import prompts as h3pr  # noqa: E402
from h3 import workflow_registry as wr  # noqa: E402


def _wf_simple():
    """微型 API 工作流：1 号空节点 + 136 号目标节点。"""
    return {
        1: {"class_type": "NodeX", "inputs": {"a": [136, 0]}},
        136: {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"width": 608}},
    }


class TestInjectMediaRefs(unittest.TestCase):
    def test_video_audio_injection_fields(self):
        wf = _wf_simple()
        n = h3stage.inject_media_refs(wf, ["ref1.mp4"], ["amb1.mp3"])
        self.assertEqual(n, 3)  # 视频 2 节点 + 音频 1 节点
        tgt = wf[136]["inputs"]
        # 槽位键（三组）
        self.assertIn("ref_videos.ref_video_0", tgt)
        self.assertIn("ref_video_audios.ref_video_audio_0", tgt)
        self.assertIn("ref_audios.ref_audio_0", tgt)
        gvc = tgt["ref_videos.ref_video_0"][0]
        la = tgt["ref_audios.ref_audio_0"][0]
        # ② 注入节点 inputs 只含预期键，且键值与目标匹配
        self.assertEqual(wf[gvc]["class_type"], "GetVideoComponents")
        self.assertEqual(list(wf[gvc]["inputs"].keys()), ["video"])
        self.assertEqual(wf[la]["class_type"], "LoadAudio")
        self.assertEqual(list(wf[la]["inputs"].keys()), ["audio"])
        lv = wf[gvc]["inputs"]["video"][0]
        self.assertEqual(wf[lv]["class_type"], "LoadVideo")
        self.assertEqual(wf[lv]["inputs"], {"file": "ref1.mp4"})
        # GVC 输出槽：images=0 / audio=1
        self.assertEqual(tgt["ref_videos.ref_video_0"], [gvc, 0])
        self.assertEqual(tgt["ref_video_audios.ref_video_audio_0"], [gvc, 1])
        self.assertEqual(tgt["ref_audios.ref_audio_0"], [la, 0])
        # 注入 id 均为数字字符串且大于已有数字 id
        for nid in (lv, gvc, la):
            self.assertIsInstance(wf[nid], dict)
            self.assertTrue(str(nid).isdigit())
            self.assertGreater(int(nid), 136)

    def test_second_slot_0based(self):
        wf = _wf_simple()
        h3stage.inject_media_refs(wf, ["a.mp4", "b.mp4"], ["x.mp3", "y.mp3"])
        tgt = wf[136]["inputs"]
        self.assertIn("ref_videos.ref_video_1", tgt)
        self.assertIn("ref_video_audios.ref_video_audio_1", tgt)
        self.assertIn("ref_audios.ref_audio_1", tgt)
        self.assertNotIn("ref_videos.ref_video_2", tgt)

    def test_guards(self):
        with self.assertRaises(Exception):
            h3stage.inject_media_refs(_wf_simple(), ["a"] * 4, [])
        with self.assertRaises(Exception):
            h3stage.inject_media_refs(_wf_simple(), [], ["a"] * 4)
        with self.assertRaises(Exception):
            h3stage.inject_media_refs({"1": {"class_type": "Other", "inputs": {}}},
                                      ["a.mp4"], [])
        self.assertEqual(h3stage.inject_media_refs(_wf_simple(), [], []), 0)


class TestMediaTagContract(unittest.TestCase):
    def test_tag_sets(self):
        p = "Use <Video 1> for motion, <Video 2>, <Audio 1> ambience. also <video 3>."
        self.assertEqual(h3pr.media_tag_set(p, "video"), {1, 2, 3})
        self.assertEqual(h3pr.media_tag_set(p, "audio"), {1})
        self.assertEqual(h3pr.media_tag_set("none", "video"), set())

    def test_missing(self):
        self.assertEqual(h3pr.missing_media_tags("has <Video 1>", 1, "video"), [])
        self.assertEqual(h3pr.missing_media_tags("no tags", 2, "video"), [1, 2])
        self.assertEqual(h3pr.missing_media_tags("has <Audio 2>", 2, "audio"), [1])
        self.assertEqual(h3pr.missing_media_tags("x", 0, "video"), [])


class TestRegistryExt(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)
        # register 需要的模板文件（UI 格式：nodes）
        self.tpl = self.d / "video_x.json"
        self.tpl.write_text(json.dumps({
            "nodes": [
                {"type": "MiniMaxH3ReferenceToVideo", "widgets_values": ["hi"]},
                {"type": "LoadImage", "widgets_values": ["a.png", "image"]},
            ],
            "links": [], "last_node_id": 2, "last_link_id": 0,
        }), encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def _entry(self, **kw):
        e = {
            "id": "video_x", "engine": "local", "stage": "r2v", "enabled": True,
            "template": str(self.tpl), "format": "ui",
            "slots": {"images": [{"role": "reference", "count": 1}],
                      "videos": [], "audios": []},
            "prompt_inject": {"node_type": "MiniMaxH3ReferenceToVideo", "widget_index": 0},
            "inject_spec": {"class_prefix": "MiniMaxH3", "positive_key": "prompt",
                            "negative_key": "negative_prompt"},
            "params": {}, "features": {"reference_videos": False, "per_segment": False,
                                       "audio": True, "negative_support": True},
        }
        e.update(kw)
        return e

    def test_template_health_no_refmedia_target(self):
        # reference_videos=true 但 inject_spec 前缀在模板中不存在 → issues（注入不可达）
        e = self._entry()
        e["slots"]["videos"] = [{"role": "reference", "count": 3}]
        e["features"]["reference_videos"] = True
        e["inject_spec"] = dict(e["inject_spec"], class_prefix="NoSuchPrefix")
        ok, issues = wr.template_health(self.d, e)
        self.assertFalse(ok)
        self.assertTrue(any("注入目标节点" in i for i in issues))

    def test_template_health_refmedia_ok(self):
        e = self._entry()
        e["slots"]["videos"] = [{"role": "reference", "count": 3}]
        e["slots"]["audios"] = [{"role": "reference", "count": 3}]
        e["features"]["reference_videos"] = True
        tpl2 = self.d / "video_y.json"
        tpl2.write_text(json.dumps({
            "nodes": [{"type": "MiniMaxH3ReferenceToVideo", "widgets_values": ["p"]},
                      {"type": "LoadImage", "widgets_values": ["a.png", "image"]}],
            "links": [], "last_node_id": 2, "last_link_id": 0,
        }), encoding="utf-8")
        e["template"] = str(tpl2)
        ok, issues = wr.template_health(self.d, e)
        self.assertTrue(ok, issues)

    def test_add_local_slots_features_kw(self):
        cap = self.d / "cap.json"
        cap.write_text(json.dumps({"workflows": []}), encoding="utf-8")
        ok, _ = wr.add_local(cap, "video_new", "tpl.json", stage="r2v",
                             slots={"images": [], "videos": [{"role": "reference", "count": 3}],
                                    "audios": [{"role": "reference", "count": 3}]},
                             features={"reference_videos": True, "per_segment": False,
                                       "audio": True, "negative_support": True})
        self.assertTrue(ok)
        cap2 = json.loads(cap.read_text(encoding="utf-8"))
        e = next(w for w in cap2["workflows"] if w["id"] == "video_new")
        self.assertEqual(e["slots"]["videos"][0]["count"], 3)
        self.assertTrue(e["features"]["reference_videos"])


if __name__ == '__main__':
    unittest.main()
