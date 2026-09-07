"""H3 成品链自定义节点（ComfyUI）：本地 TTS（F5-TTS 魔搭）+字幕烧录+音轨替换+参考音频混音。

2026-09-07 用户指示：升级后的工作流直接在 ComfyUI 获得最终成品——本项目 h3 侧链
（h3_submit 钩子）保留为引擎管线化路径；本节点=ComfyUI 工作流节点化路径（§13③ 定案）。

模型/依赖：
  - F5-TTS 模型 + vocos：~/ai/ComfyUI/models/f5-tts/（用户指示统一放 ComfyUI models）；
  - 合成执行：~/ai/tts-venv/bin/python3（独立 venv，避免污染 ComfyUI 环境）；
  - SenseVoice ASR：~/ai/ComfyUI/models/asr/sensevoice + ~/ai/asr-venv/bin/python3；
  - 业务代码：/home/Developer/videoGenerate-Model-zju/runs/h3/（tts_local_check/asr_check）。

节点：
  1. H3LocalTTS   (text, voice)            -> AUDIO(wav 路径)
  2. H3Finalize   (video, text, voice, font_size, bed_audio) -> FILEPATH(成品 mp4)
  3. H3AsrCheck   (media, text_compare)    -> TEXT / SCORE
部署：shell/deploy_h3_nodes.sh 复制本目录到 ~/ai/ComfyUI/custom_nodes/h3_finalize/
      （ComfyUI 下次重启后生效——服务重启需人工/授权，本项目不自动重启服务）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = os.environ.get("H3_REPO", "/home/Developer/videoGenerate-Model-zju")
TTS_PY = os.environ.get("H3_TTS_PY", "/home/Developer/ai/tts-venv/bin/python3")
ASR_PY = os.environ.get("H3_ASR_PY", "/home/Developer/ai/asr-venv/bin/python3")
VOICES = ["xiaoxiao", "yunxi", "aria"]


def _sh(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("fail: " + ((r.stderr or r.stdout) or "")[-600:])
    return r.stdout


def _voice_full(short: str) -> str:
    return {"xiaoxiao": "zh-CN-XiaoxiaoNeural",
            "yunxi": "zh-CN-YunxiNeural",
            "aria": "en-US-AriaNeural"}.get(str(short or "xiaoxiao"), "zh-CN-XiaoxiaoNeural")


class H3LocalTTS:
    """本地 F5-TTS 合成（克隆参考样本音色；模型在 ComfyUI models/f5-tts/）。"""

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "大家好，这是本地语音合成。"}),
            "voice": (VOICES, {"default": "xiaoxiao"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "run"
    CATEGORY = "h3"
    OUTPUT_NODE = True

    def run(self, text, voice="xiaoxiao"):
        script = str(Path(REPO) / "runs" / "h3" / "tts_local_check.py")
        ref = str(Path(REPO) / "assets" / "tts_refs" / f"{voice}.wav")
        reft = (Path(REPO) / "assets" / "tts_refs" / f"{voice}.txt").read_text(encoding="utf-8").strip()
        out = f"/tmp/h3_tts_{os.getpid()}.wav"
        _sh([TTS_PY, script, "--text", text, "--ref-file", ref,
             "--ref-text", reft, "--output", out])
        return (out,)


class H3Finalize:
    """最终成品：本地 TTS（语音+字幕 SRT）→ 烧录字幕 → 替换音轨 → 可选参考音频 -12dB 底轨混音。

    2026-09-07 通用工作流：新增可选 `video_in`(VIDEO)——直接接 SaveVideo 输出，自动保存后走成品链
    （真·一键：生成→配音→字幕→验收 同图）；video(STRING) 手动路径仍兼容。
    """

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "video": ("STRING", {"default": ""}),          # H3 生成节点输出文件路径（手动）
            "text": ("STRING", {"multiline": True, "default": ""}),
            "voice": (VOICES, {"default": "xiaoxiao"}),
        },
            "optional": {
                "video_in": ("VIDEO",),                      # 接 SaveVideo 输出（自动桥接路径）
                "bed_audio": ("STRING", {"default": ""}),   # 参考音频/配乐（-12dB 底轨）
                "font_size": ("INT", {"default": 0, "min": 0, "max": 200}),
            }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    FUNCTION = "run"
    CATEGORY = "h3"
    OUTPUT_NODE = True

    def run(self, video, text, voice="xiaoxiao", video_in=None, bed_audio="", font_size=0):
        sys.path.insert(0, str(Path(REPO) / "runs"))
        from h3 import tts as _tts
        if video_in is not None:
            # 视频对象自带 save_to（comfy_api.latest.Types.VideoContainer/VideoCodec）
            bridge = f"/tmp/h3_bridge_{os.getpid()}.mp4"
            try:
                from comfy_api.latest import Types as _Types
                video_in.save_to(bridge, format=_Types.VideoContainer("mp4"),
                                 codec=_Types.VideoCodec("h264"))
            except Exception:  # noqa: BLE001
                import av  # type: ignore
                raise RuntimeError("VIDEO 保存失败(io.Video API 不可用), 请手动填 video 路径") from None
            video = bridge
        src = Path(video)
        if not src.is_file():
            raise RuntimeError(f"视频不存在: {video}")
        out = src.with_name(src.stem + "_final.mp4")
        voice_full = _voice_full(voice)
        res = _tts.attach_speech_and_subtitle(
            src, text.strip(), out=out, voice=voice_full,
            fontsize=int(font_size or 0), backend="local")
        final = Path(res["path"])
        if bed_audio and Path(bed_audio).is_file():
            from h3 import postprocess as _pp
            mixed = final.with_name(final.stem + "_mix.mp4")
            _pp.mix_tracks(final, mixed, main=str(res.get("speech") or str(final)),
                           bed=bed_audio, main_db=0.0, bed_db=-12.0)
            final = mixed
        return (str(final),)


class H3AsrCheck:
    """本地 SenseVoice ASR（可辨析验收/台词回环比对）；模型在 ComfyUI models/asr/。"""

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "media": ("STRING", {"default": ""}),
        },
            "optional": {
                "text_compare": ("STRING", {"default": ""}),
            }}

    RETURN_TYPES = ("STRING", "FLOAT")
    RETURN_NAMES = ("text", "score")
    FUNCTION = "run"
    CATEGORY = "h3"
    OUTPUT_NODE = True

    def run(self, media, text_compare=""):
        script = str(Path(REPO) / "runs" / "h3" / "asr_check.py")
        cmd = [ASR_PY, script, str(media)]
        if text_compare:
            cmd += ["--compare", text_compare]
        out = _sh(cmd)
        text = ""
        score = -1.0
        for ln in out.splitlines():
            if ln.startswith("ASR_TEXT:"):
                text = ln.split(":", 1)[1].strip()
            elif ln.startswith("ASR_SCORE:"):
                try:
                    score = float(ln.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return (text, score)


NODE_CLASS_MAPPINGS = {"H3LocalTTS": H3LocalTTS, "H3Finalize": H3Finalize, "H3AsrCheck": H3AsrCheck}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3LocalTTS": "H3 Local TTS (F5-TTS)",
    "H3Finalize": "H3 Finalize (TTS+Subtitle+Mix)",
    "H3AsrCheck": "H3 ASR Check (SenseVoice)",
}
