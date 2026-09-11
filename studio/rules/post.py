#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio.rules.post - 后期指令层：超分 / 音频 / 字幕（空间内**只出指令、不执行**）。

为什么要有这一层：画面生成只是成片的一半 —— 超分决定清晰度上限、混音决定能不能听、
字幕决定台词有没有错字。但空间是免费 CPU 档，**不做任何转码、不下载权重、不跑推理**；
所以这里产出的是**可执行的步骤与参数**，写进生产包的 post.md 与 film.srt，
拿到包的人在**自己的机器**上执行（book-20 §4.3）。

参数全部来自本项目真机链的实测口径（runs/h3/postprocess.py、runs/h3_submit.py 的 S13 超分链、
rife 模板），不臆造模型名与耗时。
"""
from __future__ import annotations

FPS = 24

#: 超分档（模型名与耗时来自 runs/h3_submit.py S13 超分链的实测注释）
UPSCALE_PRESETS = {
    "none": {"label": "不超分", "scale": 1, "model": "", "command": "", "note": "原生分辨率交付"},
    "4x": {"label": "4x 超分", "scale": 4, "model": "RealESRGAN 4x-UltraSharp",
           "node": "ImageUpscaleWithModel",
           "command": "python3 runs/h3_submit.py --upscale 4x",
           "note": "608x352 → 2432x1408；真机实测约 5-8 分钟 / 5 秒片；失败不阻断主产物"},
}

#: 插帧档（本项目 rife 模板已打通，48fps 成片见 outputs/video_67_rife_48fps_yunxi.mp4）
INTERP_PRESETS = {
    "none": {"label": "不插帧", "fps": FPS},
    "48": {"label": "插帧到 48fps", "fps": 48,
           "note": "真机用 ComfyUI RIFE（flownet）模板；流畅度提升，快速摇镜/慢动作慎用（可能有伪影）"},
    "minterpolate": {"label": "ffmpeg 插帧到 48fps", "fps": 48,
                     "command": "python3 runs/h3/postprocess.py --interp",
                     "note": "不依赖额外权重；默认关闭（慢、可能有伪影）"},
}

#: 混音口径（给执行方一个明确起点，可按引擎侧实测微调）
MIX = {"sample_rate": 48000, "channels": 2, "loudness_lufs": -16.0,
       "dialogue_db": 0.0, "ambience_db": -18.0, "music_db": -22.0}


def upscale_plan(resolution: str = "", *, mode: str = "4x", source_size=None) -> dict:
    """超分步骤（默认 4x）。source_size 给了就顺手算出目标尺寸。"""
    p = dict(UPSCALE_PRESETS.get(str(mode or "none").lower(), UPSCALE_PRESETS["none"]))
    p["mode"] = str(mode or "none").lower()
    p["source_resolution"] = resolution
    if source_size and p.get("scale", 1) > 1:
        w, h = source_size
        p["target_size"] = (int(w) * p["scale"], int(h) * p["scale"])
        p["steps"] = ["按上面的目标尺寸超分", "先分段超分再拼接（比整片超分省一半时间）"]
    else:
        p.setdefault("steps", ["先出原生分辨率成片", "确认内容没问题后再超分（超分不改内容，只提清晰度）"])
    p["honest_note"] = "超分是**合成**清晰度，不等于原生高分辨率；交付说明里要如实标注"
    return p


def interp_plan(*, mode: str = "none") -> dict:
    """插帧步骤（可选）。"""
    p = dict(INTERP_PRESETS.get(str(mode or "none").lower(), INTERP_PRESETS["none"]))
    p["mode"] = str(mode or "none").lower()
    p["fps_target"] = p.get("fps", FPS)
    p["honest_note"] = "插帧是合成中间帧；动作剧烈时可能有伪影，验收时逐段看一遍"
    return p


def audio_plan(shots, personas=None, *, ambience: str = "room", music: str = "none") -> dict:
    """音频步骤：台词轨（模型原声）+ 环境声垫底 +（可选）配乐。

    铁律：台词**由视频模型原声说出**，不要用 TTS 链替换台词轨（音画不同步、口型对不上）。
    """
    talk = []
    t = 0.0
    for s in shots or []:
        s = s or {}
        dur = float(s.get("seconds") or 0)
        line = s.get("line") or {}
        if line.get("text"):
            talk.append({"idx": s.get("idx"), "text": line.get("text"),
                         "speaker": line.get("speaker") or "",
                         "voice": line.get("voice") or "native",
                         "start": round(t, 3), "seconds": dur})
        t += dur
    return {
        "dialogue": talk,
        "dialogue_rule": "台词由视频模型原声说出（--voice-mode native / --audio-source h3）；禁止用 TTS 链替换台词轨",
        "ambience": ambience,
        "music": music,
        "mix": dict(MIX),
        "total_seconds": round(t, 2),
        "steps": [
            "台词轨：模型原生语音（无需额外配音）；某段口型对不上就重跑该段，不要靠后期对口型",
            "环境声：按段落语义选（room / rain / none），音量约 %s dB" % MIX["ambience_db"],
            "配乐：可选，音量约 %s dB，注意不要压过台词" % MIX["music_db"],
            "响度归一：约 %s LUFS，%d kHz 立体声" % (MIX["loudness_lufs"], MIX["sample_rate"] // 1000),
            "导出后**用耳朵过一遍**：台词听不清 = 不合格（这一步机器代替不了）",
        ],
    }


def _ts(seconds: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm。"""
    ms = int(round(max(0.0, float(seconds)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def srt_from_shots(shots, *, hold: float = 0.4) -> str:
    """由**台词表原文**直出 SRT（不经 ASR，杜绝错字）。

    hold：字幕比台词多停留的秒数（读完留一点余量）。时间轴按段落累计，与逐段生成一一对应。
    """
    # 注释行前缀在 SRT 里不是标准语法，这里用 # 开头的说明 + 空行，播放器会忽略无法解析的块
    head = ["# 本字幕由台词表原文直出（不经过语音识别，不会出现错别字）",
            "# 时间轴与逐段成片一一对应；若执行方改了段长，请同步改这里", ""]
    body = []
    t = 0.0
    n = 0
    for s in shots or []:
        s = s or {}
        dur = float(s.get("seconds") or 0)
        text = str(((s.get("line") or {}).get("text")) or "").strip()
        if text:
            n += 1
            body.append("%d" % n)
            body.append("%s --> %s" % (_ts(t), _ts(t + max(0.8, dur - 0.15) + hold)))
            body.append(text)
            body.append("")
        t += dur
    return "\n".join(head + body)


def post_plan(st=None, *, upscale: str = "4x", interp: str = "none",
              ambience: str = "room", music: str = "none", burn_subtitle: bool = False) -> dict:
    """一份完整后期计划（生产包的 post.md 由它渲染）。"""
    shots = list(getattr(st, "shots", None) or []) if st is not None else []
    res = (shots[0].get("resolution") if shots else "") or ""
    return {
        "upscale": upscale_plan(res, mode=upscale),
        "interp": interp_plan(mode=interp),
        "audio": audio_plan(shots, None, ambience=ambience, music=music),
        "subtitle": {
            "source": "台词表原文（srt_from_shots 直出）",
            "file": "film.srt",
            "burn_in": bool(burn_subtitle),
            "burn_rule": "本项目真机默认不烧字幕（--no-subtitle）：字幕另附 SRT，后期按平台需要再加；烧录位置必须避开底部安全区",
            "why": "台词原文写进画面提示词会被模型画成画面字幕 —— 字幕只能在后期加",
        },
        "honest_notes": [
            "空间内**不执行**以上任何一步：超分/混音/字幕都在执行方机器上做",
            "超分与插帧都是**合成**，交付说明里要如实标注，不冒充原生高分辨率或高帧率",
            "台词轨必须是模型原声；用 TTS 链替代会导致音画不同步",
        ],
    }


def post_markdown(st=None, **kw) -> str:
    """post.md：给人看的后期指令（复制即用）。"""
    p = post_plan(st, **kw)
    L = ["# 后期指令（超分 / 音频 / 字幕）", "",
         "> 空间内**不执行**这些步骤；本节给的是可直接复制的命令与参数。", ""]
    L += ["## 一、超分", "", "- 方案：%s（%s）" % (p["upscale"]["label"], p["upscale"]["model"] or "无"),
          "- 来源分辨率：%s" % (p["upscale"].get("source_resolution") or "见 plan.json")]
    if p["upscale"].get("target_size"):
        L.append("- 目标尺寸：%d×%d" % p["upscale"]["target_size"])
    if p["upscale"].get("command"):
        L += ["", "```bash", p["upscale"]["command"], "```"]
    if p["upscale"].get("note"):
        L.append("- 实测：%s" % p["upscale"]["note"])
    L.append("- 注意：%s" % p["upscale"]["honest_note"])
    L += ["", "## 二、插帧（可选）", "", "- 方案：%s" % p["interp"]["label"]]
    if p["interp"].get("command"):
        L += ["", "```bash", p["interp"]["command"], "```"]
    if p["interp"].get("note"):
        L.append("- 说明：%s" % p["interp"]["note"])
    a = p["audio"]
    L += ["", "## 三、音频", "", "- 台词轨规则：%s" % a["dialogue_rule"],
          "- 台词 %d 句；环境声 %s；配乐 %s" % (len(a["dialogue"]), a["ambience"], a["music"]), ""]
    for it in a["dialogue"]:
        L.append("  - 第 %s 段 @%ss：%s（%s）" % (it["idx"], it["start"], it["text"], it["voice"]))
    L += ["", "混音参数：", ""]
    for k in ("sample_rate", "channels", "loudness_lufs", "dialogue_db", "ambience_db", "music_db"):
        L.append("- %s = %s" % (k, a["mix"][k]))
    L += ["", "步骤："] + ["%d. %s" % (i + 1, s) for i, s in enumerate(a["steps"])]
    s = p["subtitle"]
    L += ["", "## 四、字幕", "", "- 字幕原文：%s（%s）" % (s["file"], s["source"]),
          "- 是否烧录：%s" % ("烧录" if s["burn_in"] else "不烧录（默认，另附 SRT）"),
          "- 为什么：%s" % s["why"], "- 规则：%s" % s["burn_rule"]]
    L += ["", "## 五、必须如实说明的边界", ""] + ["- %s" % n for n in p["honest_notes"]] + [""]
    return "\n".join(L)


__all__ = ["UPSCALE_PRESETS", "INTERP_PRESETS", "MIX", "upscale_plan", "interp_plan",
           "audio_plan", "srt_from_shots", "post_plan", "post_markdown"]
