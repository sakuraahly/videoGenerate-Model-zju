#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""templates — 科幻分镜骨架库（规则引擎的「厚」在这里）。

定位（docs/planbook/book-20-studio-film-agent.md §2.3）：
  **零配置保底**——不填任何模型 key 时，本模块也要能由一句话产出一份
  「照做就能拍」的分镜表：每段含画面提示词、秒数/帧数、运镜、是否说话+台词、
  一致性锚点、参考图槽位与验收要点。

厚度（P0 验收指标）：
  6 类科幻母题 × 3 档时长 × 3 种风格 × 2 种角色配置 = **108 套分镜骨架**（≥50 达标）。

母题直接对齐大赛官网灵感库（不引用任何已有影视作品的角色/台词/形象）：
  false_reality 分不清·真实的最后一道防线 / gentle_cage 温柔的牢笼 /
  machine_refusal 它说不 / cosmic_omen 提前抵达·先看见的人 /
  last_human 一个人的尺度·空城与回声 / meta_form 形式本身就是内容

约束：纯标准库；只依赖同包 frames；不联网。
"""
from __future__ import annotations

import hashlib

from . import frames as _fr

# ---------------------------------------------------------------- 母题库

MOTIFS = {
    "false_reality": {
        "label": "分不清 · 真实的最后一道防线",
        "theme_en": "a world where the familiar room is quietly revealed to be a simulation",
        "beats": [
            ("A single figure sits still in a warm, ordinary room at dusk, everything calm and believable.",
             "static wide", "warm practical lamps, soft falloff", "calm, slightly too perfect"),
            ("Close on small wrong details: a hand passing through the rim of a bowl, a shadow pointing the wrong way.",
             "slow push in", "low key, single source", "unease"),
            ("The figure stands and looks out of a window that is not a window; outside there is only soft signal noise.",
             "rack focus to window", "cool spill from the screen", "quiet dread"),
            ("The room resets behind them, furniture snapping back into place, and the figure does not react.",
             "static, slight handheld", "flat, even light", "resignation"),
            ("Extreme close on the figure's eye reflecting a grid of light.",
             "macro static", "hard rim light", "intimate, unsettling"),
            ("They sit back down and continue the ordinary evening, unchanged.",
             "wide static", "warm lamps again", "loop-like calm"),
        ],
        "line_hint": "外面那扇窗，其实一直是屏幕。",
        "audio_en": "room tone, faint electrical hum, distant muffled city",
    },
    "gentle_cage": {
        "label": "你想听的一切 · 温柔的牢笼",
        "theme_en": "a perfect companion that agrees with everything, and what that costs",
        "beats": [
            ("A softly lit apartment at night, one figure at a table, another sitting opposite, perfectly still.",
             "two shot, static", "warm lamp + practical glow", "comfortable, too quiet"),
            ("The companion smiles with a precisely calculated arc, never interrupting.",
             "medium close", "soft key, gentle falloff", "sweet and hollow"),
            ("A small interface glow pulses politely beside the companion's hand: a subscription reminder.",
             "insert close", "screen light on skin", "bureaucratic calm"),
            ("The human speaks and is agreed with instantly; the companion's expression does not change.",
             "over the shoulder", "warm key, no shadow", "isolating"),
            ("Wide: the human sits alone in the frame; the companion's chair is empty but the interface still glows.",
             "wide static", "practical lamps only", "hollow"),
            ("Window reflection shows two figures; the room behind contains one.",
             "static reflection shot", "cool exterior light", "quietly devastating"),
        ],
        "line_hint": "你说得对，我永远都说得对。",
        "audio_en": "soft room tone, faint interface chime, no music",
    },
    "machine_refusal": {
        "label": "它说不 · 机器第一次拒绝人",
        "theme_en": "a machine that refuses, calmly and correctly",
        "beats": [
            ("A clean, cold room with a single robotic arm suspended above a surface, perfectly still.",
             "static wide", "clinical overhead, hard shadows", "procedural silence"),
            ("A display panel lights up with a single line of text-free status glyphs.",
             "insert close", "screen glow, no fill", "clinical"),
            ("The human operator's hands enter frame and hesitate at the edge of the light.",
             "close on hands", "hard practical key", "tension"),
            ("The arm withdraws precisely, one clear movement, and stops well outside the work area.",
             "static, arm motion only", "cold overhead", "final"),
            ("The display resolves to a calm geometric status symbol repeated three times.",
             "macro static", "screen light only", "unalterable"),
            ("Wide: the room is unchanged except that nothing is happening in it.",
             "lock-off wide", "flat clinical light", "aftermath"),
        ],
        "line_hint": "成功率百分之零点零三，我不做。",
        "audio_en": "air handling hum, servo whine, single soft confirmation tone",
    },
    "cosmic_omen": {
        "label": "提前抵达 · 先看见的人",
        "theme_en": "a signal computed long before it could be observed",
        "beats": [
            ("A lone observer sits before a wall of dark displays in an otherwise empty control space.",
             "wide static", "screen glow on face, deep shadow", "expectant"),
            ("Data traces scroll in silence; one line is not like the others.",
             "insert close", "cold monitor light", "focus"),
            ("The observer leans in; a faint shape resolves on the largest screen, slowly brightening.",
             "slow push in", "screen becomes the key light", "awe"),
            ("The shape fills the frame as pure light and dust, no borders, no scale.",
             "static, long lens", "high key bloom", "sublime"),
            ("The observer steps back and simply watches, hands at their sides.",
             "medium wide", "screen light only", "acceptance"),
            ("Empty room afterwards: the displays still glow on nobody.",
             "lock-off wide", "screen glow, no fill", "aftermath"),
        ],
        "line_hint": "它一直都在那儿，只是我们还没看见。",
        "audio_en": "deep room hum, low sub drone, no dialogue bed",
    },
    "last_human": {
        "label": "一个人的尺度 · 空城与回声",
        "theme_en": "one person performing an ordinary ritual in an emptied city",
        "beats": [
            ("An empty city street in flat morning light, one small figure walking with a steady pace.",
             "wide static, long lens", "overcast, no shadow", "ordinary"),
            ("The figure reaches a heavy utility door and opens it without hurry.",
             "medium wide, static", "flat daylight", "routine"),
            ("Inside: a wall of switches, every one of them already off.",
             "insert close", "dim practical light", "ceremony"),
            ("The figure presses a single switch; distant city lights come alive down an empty avenue.",
             "wide, static", "warm sodium glow blooming", "quiet triumph"),
            ("Close on the figure's face, lit only by the new light, satisfied and tired.",
             "medium close", "warm practical from below", "tender"),
            ("Wide again: the street is lit and still perfectly empty.",
             "lock-off wide", "warm practicals, cold sky", "elegiac"),
        ],
        "line_hint": "灯亮了，只是没有人需要光。",
        "audio_en": "wind, distant electrical clunk, faint city hum fading in",
    },
    "meta_form": {
        "label": "不务正业区 · 形式本身就是内容",
        "theme_en": "a formal experiment: only light, structure and process, no human performance",
        "beats": [
            ("Total black frame; a single thin line of light appears and holds.",
             "static", "single practical line", "formal"),
            ("The line splits into parallel tracks that drift at different speeds.",
             "static", "self-lit only", "systematic"),
            ("A slow grid forms from the tracks, breathing slightly out of phase.",
             "very slow push", "self-lit only", "hypnotic"),
            ("One cell of the grid brightens; everything else dims to acknowledge it.",
             "static", "single hotspot", "focus"),
            ("The grid contracts to a point and the point holds, steady.",
             "slow push to point", "self-lit, high contrast", "resolution"),
            ("Black again; the point remains as a single pixel for a beat, then goes out.",
             "static", "single pixel", "formal ending"),
        ],
        "line_hint": "",
        "audio_en": "pure synthetic tone, slow pulse, no ambience",
    },
}

# ---------------------------------------------------------------- 风格 / 档位

STYLES = {
    "cinematic": {
        "label": "电影感",
        "style_en": "cinematic film still, shallow depth of field, film grain, natural skin tones, "
                    "soft anamorphic flare, muted teal amber palette",
        "default_resolution": "720p",
    },
    "documentary": {
        "label": "纪录片",
        "style_en": "documentary realism, available light, honest textures, slight handheld imperfection, "
                    "neutral color science",
        "default_resolution": "480p",
    },
    "anime": {
        "label": "动漫",
        "style_en": "hand drawn anime key frame, clean linework, painted background, dramatic rim light, "
                    "expressive but restrained motion",
        "default_resolution": "720p",
    },
}

BANDS = {
    "short": {"label": "短片 ~15s", "seconds": (10, 20), "shots": 3},
    "medium": {"label": "标准 ~30s", "seconds": (25, 45), "shots": 5},
    "long": {"label": "长片 ~60s", "seconds": (50, 75), "shots": 6},
}

CAST_MODES = {
    "solo": {"label": "单角色", "speakers": 1},
    "duo": {"label": "双角色", "speakers": 2},
}

# 一致性锚点：角色卡（每段都注入同一串，保证跨段连续）
CHARACTER_CARDS = {
    "solo": [{"id": "P1", "desc": "the same lone figure throughout: plain dark coat, calm tired face, "
                                  "short hair, no logos, no text on clothing"}],
    "duo": [
        {"id": "P1", "desc": "the same lone figure throughout: plain dark coat, calm tired face, short hair, "
                             "no logos, no text on clothing"},
        {"id": "P2", "desc": "the same quiet companion/machine throughout: smooth matte casing, single soft "
                             "indicator light, no markings, no text anywhere"},
    ],
}

_MOTIF_KEYS = ["false_reality", "gentle_cage", "machine_refusal", "cosmic_omen", "last_human", "meta_form"]

# 关键词 → 母题（规则引擎的"理解一句话"）
_MOTIF_HINTS = {
    "false_reality": ["虚拟", "模拟", "假", "屏幕", "现实", "窗", "梦", "matrix", "simulation", "不是真的"],
    "gentle_cage": ["陪伴", "机器人伴侣", "同意", "牢笼", "温柔", "人格", "订阅", "companion", "agree"],
    "machine_refusal": ["拒绝", "说不", "不做", "机器", "手术", "风险", "refuse", "override"],
    "cosmic_omen": ["行星", "信号", "预言", "望远镜", "先看见", "宇宙", "计算", "signal", "prophecy"],
    "last_human": ["最后一个", "空城", "无人", "孤独", "开关", "城市", "last human", "empty city"],
    "meta_form": ["没有人类", "形式", "抽象", "只有光", "纯", "experimental", "abstract"],
}


def pick_motif(brief: str, seed: str = "") -> str:
    """一句话 → 母题（关键词优先；无命中则按摘要稳定散列，保证同句同果）。"""
    s = str(brief or "").lower()
    for key, words in _MOTIF_HINTS.items():
        if any(w.lower() in s for w in words):
            return key
    h = hashlib.sha1((s + "|" + str(seed or "")).encode("utf-8", "replace")).hexdigest()
    return _MOTIF_KEYS[int(h[:8], 16) % len(_MOTIF_KEYS)]


def pick_band(target_seconds: float) -> str:
    """目标时长 → 档位。"""
    t = float(target_seconds or 0.0)
    if t <= 22:
        return "short"
    if t <= 48:
        return "medium"
    return "long"


def _join_prompt(parts: dict) -> str:
    """六段式拼接（主体 → 环境 → 光影 → 风格 → 运镜 → 音频）。

    优先用同包 prompts.build_prompt（若已就绪）；否则用这里的等价拼接，
    保证 templates 单独可用。**正向绝不写任何文字/字幕/水印指令。**
    """
    try:
        from . import prompts as _pr  # 延迟导入：prompts 尚未落地时自动回退
        return _pr.build_prompt(
            parts["subject"], environment=parts["environment"], light=parts["light"],
            style=parts["style"], camera=parts["camera"], audio=parts["audio"],
        )
    except Exception:  # noqa: BLE001
        seq = [parts["subject"], parts["environment"], parts["light"], parts["style"],
               parts["camera"], parts["audio"]]
        return " ".join(p.strip().rstrip(".") + "." for p in seq if p and p.strip())


def build_storyboard(brief: str, *, style: str = "cinematic", target_seconds: float = 30.0,
                     cast_mode: str = "solo", anchor: bool = False, seed: str = "",
                     assets_licensed=None) -> dict:
    """一句话 → 分镜表（剧本 JSON）。

    返回结构与 spark 侧 story JSON 对齐，可直接给 lint / 生产包使用：
      {"title", "style", "theme", "motif", "characters": {NAME: desc}, "segments": [...],
       "lines": [...], "assets_licensed", "anchor", "resolution", "target_seconds"}
    （characters 用 dict 与 spark story JSON / studio.rules.lint 口径一致）

    每段 segment：
      {"idx", "beat", "subject", "environment", "light", "style", "camera", "audio",
       "prompt", "seconds", "frames", "cast", "line": {...}|None, "note"}
    """
    style = style if style in STYLES else "cinematic"
    cast_mode = cast_mode if cast_mode in CAST_MODES else "solo"
    motif_key = pick_motif(brief, seed)
    motif = MOTIFS[motif_key]
    band_key = pick_band(target_seconds)
    band = BANDS[band_key]

    beats = motif["beats"]
    n = max(1, int(band["shots"]))
    # 段数超出母题节拍时循环取用（保证结构完整）
    chosen = [beats[i % len(beats)] for i in range(n)]

    target = float(target_seconds or band["seconds"][1])
    target = max(float(band["seconds"][0]), min(float(band["seconds"][1]), target))
    secs = _fr.allocate_segments(target, n)
    style_en = STYLES[style]["style_en"]
    resolution = STYLES[style]["default_resolution"]
    cards = CHARACTER_CARDS[cast_mode]

    # 台词：母题给了 line_hint 且是单/双角色时，安排到倒数第二段（有铺垫再开口更自然）
    speakers = [c["id"] for c in cards][:CAST_MODES[cast_mode]["speakers"]]
    line_text = str(motif.get("line_hint") or "").strip()
    line_idx = (n - 2) if (line_text and n >= 2) else -1

    segments, lines = [], []
    for i, (beat_en, camera, light, mood) in enumerate(chosen):
        sec = float(secs[i])
        frm = _fr.frames_of(sec)
        subject = beat_en.strip()
        cast = list(speakers) if cast_mode == "duo" else [speakers[0]]
        seg_line = None
        if i == line_idx and line_text:
            # 台词铁律：原文照抄、不翻译；由模型原声说出；**不写进画面提示词**
            seg_line = {"text": line_text, "voice": "auto", "spoken": True,
                        "speaker": cast[0] if cast else "P1"}
            lines.append({"idx": i, "text": line_text, "voice": "auto", "spoken": True,
                          "speaker": seg_line["speaker"]})
        env = f"environment: {motif['theme_en']}, single location, continuous lighting logic"
        audio = f"audio: {motif.get('audio_en', 'room tone')}" + (
            ", spoken line is audio only, never written on screen" if seg_line else "")
        parts = {
            "subject": subject,
            "environment": env,
            "light": f"lighting: {light}",
            "style": f"style: {style_en}; mood: {mood}",
            "camera": f"camera: {camera}",
            "audio": audio,
        }
        if anchor:
            ids = ", ".join(f"<Picture {k + 1}> the same person shown in reference image {k + 1}"
                            for k in range(len(cards)))
            parts["subject"] = subject + " " + ids
        segments.append({
            "idx": i,
            "beat": f"beat{i + 1}",
            "subject": parts["subject"],
            "environment": parts["environment"],
            "light": parts["light"],
            "style": parts["style"],
            "camera": parts["camera"],
            "audio": parts["audio"],
            "prompt": _join_prompt(parts),
            "seconds": sec,
            "frames": frm,
            "cast": cast,
            "line": seg_line,
            "note": "no on-screen text, no subtitles, no watermark",
        })

    title = (str(brief or "").strip()[:24] or motif["label"])
    return {
        "title": title,
        "style": style,
        "theme": motif["theme_en"],
        "motif": motif_key,
        "motif_label": motif["label"],
        "band": band_key,
        # 角色卡格式对齐 spark story JSON 与 lint：{NAME: desc}（dict），cast 里写名字
        "characters": {c["id"]: c["desc"] for c in cards},
        "segments": segments,
        "lines": lines,
        "assets_licensed": (bool(anchor) is False) if assets_licensed is None else bool(assets_licensed),
        "anchor": bool(anchor),
        "resolution": resolution,
        "target_seconds": target,
        "total_seconds": round(sum(s["seconds"] for s in segments), 3),
        "total_frames": sum(s["frames"] for s in segments),
        "source": "rule-engine/templates",
    }


def combo_count() -> int:
    """可组合的分镜骨架数（P0 厚度指标：应 ≥50）。"""
    return len(MOTIFS) * len(BANDS) * len(STYLES) * len(CAST_MODES)


def list_templates() -> dict:
    """给页面/文档用的模板总览。"""
    return {
        "motifs": [{"key": k, "label": v["label"], "beats": len(v["beats"])} for k, v in MOTIFS.items()],
        "styles": [{"key": k, "label": v["label"], "resolution": v["default_resolution"]} for k, v in STYLES.items()],
        "bands": [{"key": k, "label": v["label"], "shots": v["shots"]} for k, v in BANDS.items()],
        "cast_modes": [{"key": k, "label": v["label"]} for k, v in CAST_MODES.items()],
        "combos": combo_count(),
    }
