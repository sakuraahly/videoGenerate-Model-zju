"""八审：TTS 完成钩子（_run_tts_hook）双分支测试——无 ffmpeg（monkeypatch h3.tts / h3.postprocess）。

拦截两类曾被宽泛 except 吞掉的 UnboundLocalError：
  1. _voice 仅在 fast 分支赋值、else 分支引用（七审 1d3e3bb 引入，P1a 前 agent 唯一路径）；
  2. _tj 仅 CLI 未给 tts_text 时赋值、task_folder 为真即引用（六审 93c1533 引入）。

另覆盖八审要求的「代码缺陷 vs 环境异常」分类：NameError/AttributeError → tts_code_error，
ValueError 等环境异常 → tts_error；两者均不阻断且返回解析后的台词文本（postprocess 语义保留）。
"""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

import h3_submit
from h3 import postprocess as h3_pp
from h3 import tts as h3_tts


def _args(**kw):
    base = {"tts_text": "", "tts_voice": "", "postprocess": ""}
    base.update(kw)
    return argparse.Namespace(**base)


def _gp():
    return argparse.Namespace(seconds=5)


class TestTtsHookBranches(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.proj = self.root / "proj"
        self.outdir = self.proj / "outputs"
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.vid = self.outdir / "video_zz.mp4"
        self.vid.write_bytes(b"fake")

    def tearDown(self):
        self._td.cleanup()

    # ---------------------------------------------------------------- 1.1
    def test_non_fast_voice_defined_and_used(self):
        """非 fast（P1a 前 agent 唯一路径）：else 分支 _voice 必须先归一再引用。"""
        with mock.patch.object(h3_tts, "probe_duration", return_value=5.0), \
             mock.patch.object(h3_submit, "_log_event") as log, \
             mock.patch.object(h3_tts, "attach_speech_and_subtitle", return_value={
                 "path": self.outdir / "video_zz_v2.mp4", "speech_dur": 3.0,
                 "srt": self.outdir / "video_zz.srt"}) as attach:
            txt = h3_submit._run_tts_hook(
                self.proj, None, _args(tts_text="你好世界", tts_voice="zh-CN-YunxiNeural"),
                [self.vid], _gp())
        self.assertEqual(txt, "你好世界")
        attach.assert_called_once()
        self.assertEqual(attach.call_args.kwargs["voice"], "zh-CN-YunxiNeural")
        self.assertTrue(any("voice=zh-CN-YunxiNeural" in str(c) for c in log.call_args_list))

    # ---------------------------------------------------------------- 1.2
    def test_fast_cli_text_with_task_folder_no_job(self):
        """fast + CLI tts_text + task_folder 为真（job.json 缺失→read_json 返回 None→{}）：
        _tj 必须无条件初始化，不得 UnboundLocalError。"""
        task_folder = self.proj / "workflows" / "h3_x"
        task_folder.mkdir(parents=True)
        prep = {"speech": self.outdir / "sp.mp3", "srt": self.outdir / "sp.srt", "speech_dur": 3.0}
        with mock.patch.object(h3_tts, "probe_duration", return_value=5.0), \
             mock.patch.object(h3_submit, "_log_event"), \
             mock.patch.object(h3_tts, "prepare_speech", return_value=prep) as prep_m, \
             mock.patch.object(h3_tts, "replace_audio_only", return_value=None) as rep_m, \
             mock.patch.object(h3_pp, "process", return_value=None) as proc_m:
            txt = h3_submit._run_tts_hook(
                self.proj, task_folder,
                _args(tts_text="配音台词", tts_voice="zh-CN-YunxiNeural", postprocess="fast"),
                [self.vid], _gp())
        self.assertEqual(txt, "配音台词")
        prep_m.assert_called_once()
        self.assertEqual(prep_m.call_args.kwargs["voice"], "zh-CN-YunxiNeural")
        proc_m.assert_called_once()
        self.assertEqual(proc_m.call_args.kwargs["srt"], prep["srt"])
        rep_m.assert_called_once()

    def test_fast_cli_text_no_task_folder(self):
        """fast + CLI tts_text + task_folder=None：同样必须走通（_tj={} 兜底）。"""
        prep = {"speech": self.outdir / "sp.mp3", "srt": self.outdir / "sp.srt", "speech_dur": 3.0}
        with mock.patch.object(h3_tts, "probe_duration", return_value=5.0), \
             mock.patch.object(h3_submit, "_log_event"), \
             mock.patch.object(h3_tts, "prepare_speech", return_value=prep) as prep_m, \
             mock.patch.object(h3_tts, "replace_audio_only", return_value=None), \
             mock.patch.object(h3_pp, "process", return_value=None):
            txt = h3_submit._run_tts_hook(
                self.proj, None,
                _args(tts_text="只走CLI", tts_voice="zh-CN-XiaoxiaoNeural", postprocess="fast"),
                [self.vid], _gp())
        self.assertEqual(txt, "只走CLI")
        self.assertEqual(prep_m.call_args.kwargs["voice"], "zh-CN-XiaoxiaoNeural")

    # ---------------------------------------------------------------- 任务记录回读
    def test_voice_and_text_from_job_record(self):
        """CLI 未给 tts_text：从任务记录回读文本与音色（resume/续传路径）。"""
        task_folder = self.proj / "workflows" / "h3_y"
        task_folder.mkdir(parents=True)
        (task_folder / "job.json").write_text(json.dumps(
            {"tts_text": "来自记录的台词", "tts_voice": "zh-CN-YunxiNeural"}), encoding="utf-8")
        with mock.patch.object(h3_tts, "probe_duration", return_value=5.0), \
             mock.patch.object(h3_submit, "_log_event"), \
             mock.patch.object(h3_tts, "attach_speech_and_subtitle", return_value={
                 "path": self.outdir / "v.mp4", "speech_dur": 2.0, "srt": None}) as attach:
            txt = h3_submit._run_tts_hook(self.proj, task_folder, _args(), [self.vid], _gp())
        self.assertEqual(txt, "来自记录的台词")
        self.assertEqual(attach.call_args.args[1], "来自记录的台词")
        self.assertEqual(attach.call_args.kwargs["voice"], "zh-CN-YunxiNeural")

    # ---------------------------------------------------------------- 无台词
    def test_no_tts_text_returns_empty(self):
        with mock.patch.object(h3_submit, "_log_event") as log, \
             mock.patch.object(h3_tts, "attach_speech_and_subtitle") as attach:
            txt = h3_submit._run_tts_hook(self.proj, None, _args(), [self.vid], _gp())
        self.assertEqual(txt, "")
        attach.assert_not_called()
        log.assert_not_called()

    # ---------------------------------------------------------------- 分类
    def test_code_bug_marked_tts_code_error(self):
        """代码缺陷（AttributeError）→ tts_code_error + TTS_CODE_ERROR 标记（不是“不影响主产物”提示）。"""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(h3_tts, "probe_duration", return_value=5.0), \
             mock.patch.object(h3_tts, "attach_speech_and_subtitle",
                               side_effect=AttributeError("boom")), \
             mock.patch.object(h3_submit, "_log_event") as log, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            txt = h3_submit._run_tts_hook(
                self.proj, None, _args(tts_text="台词", tts_voice="zh-CN-XiaoxiaoNeural"),
                [self.vid], _gp())
        self.assertEqual(txt, "台词")  # postprocess 分支判据语义保留
        self.assertTrue(any("tts_code_error err=AttributeError" in str(c) for c in log.call_args_list))
        self.assertIn("TTS_CODE_ERROR", out.getvalue())
        self.assertIn("代码错误", err.getvalue())

    def test_env_failure_marked_tts_error(self):
        """环境异常（ValueError，如源视频截断守卫/合成失败）→ tts_error（非代码错误）。"""
        with mock.patch.object(h3_tts, "probe_duration", return_value=3.0), \
             mock.patch.object(h3_submit, "_log_event") as log, \
             mock.patch.object(h3_tts, "attach_speech_and_subtitle"):
            txt = h3_submit._run_tts_hook(
                self.proj, None, _args(tts_text="台词", tts_voice="zh-CN-XiaoxiaoNeural"),
                [self.vid], _gp())
        self.assertEqual(txt, "台词")
        # 时长守卫：3.0 < 5*0.8=4.0 → ValueError → tts_error（非 tts_code_error）
        self.assertTrue(any("tts_error err=ValueError" in str(c) for c in log.call_args_list))
        self.assertFalse(any("tts_code_error" in str(c) for c in log.call_args_list))


if __name__ == "__main__":
    unittest.main()
