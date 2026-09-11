#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompts — 六段式提示词组装 + 正/负词库（纯函数，零依赖）。

三条铁律（改代码前先读；来源 book-20 §2.3-3 + runs/h3/prompts.py 顶部三次实测记录）：

  (a) **正向提示词里绝不能出现任何关于「文字 / 字幕 / 水印」的指令。**
      H3 只要在正向里读到「关于文字的指令性文字」，就会把它当成要渲染的字幕画进画面——
      实测（同一提示词、同种子，只改文字条款）：
        ① 中文前缀「超高清摄影，8K文字渲染，矢量级笔画锐度，无抗锯齿失真」→ 画面多出乱码「无抗锡纹九锐朱度」；
        ② 换成英文前缀 ultra-high-definition photography / 8K text rendering … → 画面多出「Ultra-high-devi-gtifics」；
        ③ 去掉前缀、把要求融进长描述句 → 画面仍多出「Pant国ゥ格』爱戯」。
      所以本模块定案：
        · want_text=False（默认：画面不要任何文字，字幕由后期烧录）时，正向**一个文字类词都不生成**；
        · 要压掉字幕/水印，只能写进 negative_prompt()（负向词不参与渲染）；
        · build_prompt() 对**每一段**都跑 sanitize_positive()，把越界的**条款整条丢掉**——
          宁可少一句风格描述，也不冒「指令被画成画面文字」的风险。
      注：runs/h3/prompts.py::NO_TEXT_POS 仍把 "no subtitles, no captions" 写进正向（历史折中）；
      本包按 spark 定案取**更严的一侧**——正向只字不提文字，判定函数见 has_text_instruction()。

  (b) **六段顺序固定：主体 → 环境 → 光影 → 风格 → 运镜 → 音频**（见 SECTIONS 常量，勿改顺序）。
      同一段落在不同分镜里的位置一致 → 模型注意力分布稳定，风格串不会被环境描述冲散。

  (c) **输出英文提示词**（项目定案）。
      STYLE_PRESETS / CAMERA_PRESETS / 音频条款 / 负向词表**全部英文**；本模块不做翻译——
      subject 等自由段由上层（模板库 / Agent）写成英文；中文只允许出现在
      「确实要画在画面上的字」（招牌原文）里，而默认口径连这种都不生成。

公开 API：
  build_prompt(subject, *, environment, light, style, camera, audio, extra, want_text) -> str
  prompt_sections(...)                      # 六段清洗后的文本（键序 = SECTIONS），供页面逐段展示
  negative_prompt(*, want_text=False) -> str
  sanitize_positive(text, *, want_text=False) / has_text_instruction(text, *, want_text=False)
  STYLE_PRESETS / CAMERA_PRESETS / SECTIONS / TEXT_INSTRUCTION_TERMS / NEG_* 词库常量
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# (b) 六段顺序（**定案，勿改**）：主体 → 环境 → 光影 → 风格 → 运镜 → 音频
# ---------------------------------------------------------------------------
SECTIONS = ("subject", "environment", "light", "style", "camera", "audio")
SECTION_LABELS_CN = {
    "subject": "主体",
    "environment": "环境",
    "light": "光影",
    "style": "风格",
    "camera": "运镜",
    "audio": "音频",
}

# ---------------------------------------------------------------------------
# (c) 风格库（英文串；键名与 book-20「电影感 / 纪录片 / 动漫」三档对齐）
# ---------------------------------------------------------------------------
STYLE_PRESETS = {
    "cinematic": ("cinematic film still, 35mm anamorphic lens, shallow depth of field, "
                  "natural film grain, high dynamic range, photorealistic detail, "
                  "dramatic contrasting composition"),
    "documentary": ("documentary photography, handheld realism, natural available light, "
                    "candid unposed moment, realistic textures, muted palette, no stylisation"),
    "anime": ("2D anime key visual, cel-shaded colouring, clean line art, vivid saturated palette, "
              "hand-painted background, studio-quality animation frame"),
    "noir": ("black-and-white film noir, hard low-key lighting, deep shadows, "
             "shadow patterns through half-open blinds, drifting smoke haze, 1950s crime drama mood"),
    "cyberpunk": ("neo-noir cyberpunk, neon-drenched night street, wet reflective asphalt, "
                  "volumetric haze, teal and magenta palette, retro-futuristic architecture"),
}

#: 中文风格名 → 预设键（页面给中文、提示词出英文）
STYLE_ALIASES_CN = {
    "电影感": "cinematic",
    "电影": "cinematic",
    "纪录片": "documentary",
    "纪实": "documentary",
    "动漫": "anime",
    "动画": "anime",
    "黑色电影": "noir",
    "赛博朋克": "cyberpunk",
}

# ---------------------------------------------------------------------------
# 运镜库（英文串；键名给 Agent / 模板库用，页面上也能直接展示）
# ---------------------------------------------------------------------------
CAMERA_PRESETS = {
    "static": "static locked-off shot on a tripod, no camera movement",
    "slow_push_in": "slow dolly push-in toward the subject, smooth steady speed",
    "push_out": "slow dolly pull-back revealing the surroundings",
    "pan_left": "smooth horizontal pan to the left at constant speed",
    "pan_right": "smooth horizontal pan to the right at constant speed",
    "tilt_up": "vertical tilt upward from the ground to the sky",
    "handheld": "handheld camera with subtle natural shake, documentary immediacy",
    "crane_up": "crane shot rising upward and revealing the wider scene",
    "orbit": "slow orbital arc around the subject at a steady radius",
}

CAMERA_ALIASES_CN = {
    "固定": "static",
    "静止": "static",
    "推近": "slow_push_in",
    "慢推": "slow_push_in",
    "拉远": "push_out",
    "左摇": "pan_left",
    "右摇": "pan_right",
    "上摇": "tilt_up",
    "手持": "handheld",
    "升镜": "crane_up",
    "环绕": "orbit",
}

# ---------------------------------------------------------------------------
# 音频段条款（语义搬 runs/h3/prompts.py::SPEECH_POS / NO_SPEECH_POS，措辞已英文化）
# ⚠️ 无台词段光写 "no speech" 不够：H3 仍会让人物**动嘴**，而拼接时其乱语音轨被剔除
#    → 成片「有口型、没声音」。必须显式要求「嘴闭着、嘴唇不动」（2026-09-10 现场定案）。
# ---------------------------------------------------------------------------
AUDIO_SPEECH_PRESET = ("clear articulate speech, precise consonants, natural lip movement matching "
                       "the spoken words, dialogue clearly audible above the ambience, "
                       "clean close-miked voice")
AUDIO_AMBIENT_PRESET = ("ambient sound only, no human voice, no spoken words, the character stays "
                        "silent with the mouth closed and the lips still")

# ---------------------------------------------------------------------------
# 负向词库（**不参与渲染**，所以「不要文字 / 不要水印」只能写在这里）
# ---------------------------------------------------------------------------
NEG_QUALITY = ("low resolution, blurry, out of focus, soft focus, jpeg artifacts, heavy compression, "
               "oversaturated colours, blown-out highlights, crushed blacks, flat grey lighting, "
               "still image, slideshow, frozen frame, stuttering motion")
NEG_MORPH = ("warped anatomy, deformed hands, extra fingers, extra limbs, fused fingers, distorted "
             "face, asymmetric eyes, melting features, inconsistent identity between shots, "
             "flickering, temporal jitter, ghosting trails, duplicated characters")
#: 画质类文字负向词：字可以出现（want_text=True）时也要压「乱码 / 错字 / 糊字 / 重影」
NEG_TEXT_BAN = ("blurry illegible lettering, garbled or wrong characters, missing strokes, extra "
                "strokes, doubled or ghosted glyphs, warped or morphing letterforms, melting "
                "strokes, misspelled words, distorted typography")
#: 「画面绝对不要任何文字」条款（want_text=False 默认口径；字幕我们后期烧录）
NEG_NO_TEXT = ("on-screen subtitles, burned-in captions, karaoke text, floating text overlay, "
               "letters over the image, foreground sign lettering, text rendered on screen, "
               "any written words on screen, lower-third banners, credit roll")
#: 水印/署名：与「字幕」是两回事，任何分支都不要
NEG_WATERMARK = ("watermark, logo, signature, stamp, copyright mark, channel bug, ui overlay, "
                 "timestamp overlay, decorative border frame")

# ---------------------------------------------------------------------------
# (a) 铁律判定词表
#   · TEXT_INSTRUCTION_TERMS（硬禁）：关于「文字/字幕/水印」的**指令类**表述 —— 任何时候都不许进正向
#     （模型会把这类指令本身画成画面文字，见模块 docstring 实测记录）；
#   · TEXT_CONTENT_TERMS（软禁）：bare "text / letter / written" 这类**可指内容**的词 ——
#     want_text=False（默认：画面不要字）时禁；want_text=True（招牌/门牌确实要出字）时放行，
#     因为那时正向写的是「牌子上写着 X」这种内容句，而不是渲染指令。
# ---------------------------------------------------------------------------
TEXT_INSTRUCTION_TERMS = (
    # 英文（小写子串匹配）
    "subtitle", "caption", "karaoke", "watermark", "logo", "lettering", "typography",
    "typeface", "font", "text overlay", "overlay text", "on-screen text", "on screen text",
    "rendered text", "text rendering", "title card", "lower third", "chyron", "credit roll",
    "end card", "ui overlay", "timestamp", "signature",
    # 中文
    "字幕", "水印", "文字", "字体", "字型", "字号", "标题卡", "角标", "台标", "落款",
)
TEXT_CONTENT_TERMS = ("text", "texts", "letter", "letters", "written", "words on")

_CLAUSE_SPLIT = re.compile(r"[,;\uFF0C\uFF1B\n]+")
_SOFT_TEXT_PATTERNS = tuple(re.compile(r"\b%s\b" % re.escape(w)) for w in TEXT_CONTENT_TERMS)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def has_text_instruction(text: str, *, want_text: bool = False) -> bool:
    """这段文本是否含「关于文字/字幕/水印」的表述 —— 铁律 (a) 的判定函数。

    want_text=False（默认）：硬禁词 + 软禁词都算命中；
    want_text=True：只算硬禁词（放行 "a wooden sign reading …" 这类**内容句**）。
    """
    low = str(text or "").lower()
    if any(t in low for t in TEXT_INSTRUCTION_TERMS):
        return True
    if want_text:
        return False
    return any(p.search(low) for p in _SOFT_TEXT_PATTERNS)


def sanitize_positive(text: str, *, want_text: bool = False) -> str:
    """清洗一段正向文本：把触犯铁律 (a) 的**条款整条剔除**，其余按原顺序保留。

    按中英文逗号 / 分号 / 换行切条款（提示词是「逗号短语流」，**切条款**比切词安全：
    切词会留下残句，残句反而更容易被模型当成要渲染的文字）。
    """
    kept = []
    for clause in _CLAUSE_SPLIT.split(str(text or "")):
        c = clause.strip()
        if not c or has_text_instruction(c, want_text=want_text):
            continue
        kept.append(c)
    return ", ".join(kept)


def text_instruction_clauses(prompt: str) -> list:
    """列出正向提示词里**违反铁律 (a)** 的条款（提交前的最后一道闸；合规时返回 []）。"""
    return [c.strip() for c in _CLAUSE_SPLIT.split(str(prompt or ""))
            if c.strip() and has_text_instruction(c.strip())]


def contains_cjk(text: str) -> bool:
    """文本里是否有中日韩字符（铁律 (c)：正向应为英文；本模块不翻译，只提供自检）。"""
    return bool(_CJK_RE.search(str(text or "")))


def _resolve(preset_map: dict, alias_map: dict, value) -> str:
    """预设键 / 中文别名 / 自写英文串 → 实际写进提示词的串（空值返回 ""）。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if s.lower() in preset_map:
        return preset_map[s.lower()]
    if s in alias_map:
        return preset_map[alias_map[s]]
    return s


def style_text(style) -> str:
    """风格段文本：预设键（或中文别名）→ 英文预设串；自写串原样返回；"" → 不写风格段。"""
    return _resolve(STYLE_PRESETS, STYLE_ALIASES_CN, style)


def camera_text(camera) -> str:
    """运镜段文本：预设键（或中文别名）→ 英文预设串；自写串原样返回；"" → 不写运镜段。"""
    return _resolve(CAMERA_PRESETS, CAMERA_ALIASES_CN, camera)


def prompt_sections(subject, *, environment: str = "", light: str = "", style: str = "cinematic",
                    camera: str = "", audio: str = "", extra: str = "",
                    want_text: bool = False) -> dict:
    """六段各自**清洗后**的文本（键序 = SECTIONS，另加 extra 键）。

    给页面「逐段对照」用：哪一段被铁律 (a) 剔空了，一眼能看见（剔空 = 该段整条越界）。
    """
    return {
        "subject": sanitize_positive(subject, want_text=want_text),
        "environment": sanitize_positive(environment, want_text=want_text),
        "light": sanitize_positive(light, want_text=want_text),
        "style": sanitize_positive(style_text(style), want_text=want_text),
        "camera": sanitize_positive(camera_text(camera), want_text=want_text),
        "audio": sanitize_positive(audio, want_text=want_text),
        "extra": sanitize_positive(extra, want_text=want_text),
    }


def build_prompt(subject, *, environment: str = "", light: str = "", style: str = "cinematic",
                 camera: str = "", audio: str = "", extra: str = "",
                 want_text: bool = False) -> str:
    """按**固定六段顺序**组装英文正向提示词。

    顺序：**主体 → 环境 → 光影 → 风格 → 运镜 → 音频**（空段自动跳过，不留空逗号）；
    extra 追加在六段之后（补充镜头细节，不影响六段相对顺序）。
    各参数都可用**预设键**（STYLE_PRESETS / CAMERA_PRESETS）或**自写英文串**；传 "" 表示该段不写。
    style 默认 "cinematic"；camera 默认 ""（不指定运镜 = 交给模型，避免每条都推镜）。

    ⚠️ **铁律 (a)**：want_text=False（默认）时，输出里**不可能出现任何文字/字幕/水印指令**——
    每一段都过 sanitize_positive()，命中即整条剔除（含中文「字幕/水印/文字/字体」与英文
    subtitle / caption / watermark / logo / font / typography / text rendering / title card 等）。
    「画面里不要字幕」这类要求请写进 negative_prompt()——正向只字不提文字，是本项目定案。
    ⚠️ **铁律 (c)**：本函数**不翻译**；subject/environment/... 由上层写成英文
    （contains_cjk() 可做自检，模板库/Agent 负责产出英文串）。
    """
    secs = prompt_sections(subject, environment=environment, light=light, style=style,
                           camera=camera, audio=audio, extra=extra, want_text=want_text)
    parts = [secs[k] for k in SECTIONS if secs.get(k)]
    if secs.get("extra"):
        parts.append(secs["extra"])
    return ", ".join(parts)


def negative_prompt(*, want_text: bool = False) -> str:
    """负向提示词（**不参与渲染** —— 字幕/水印这类压制只能写在这里）。

    want_text=False（默认，画面不要任何文字）：画质 + 形变 + **绝对不要文字** + 水印；
    want_text=True（招牌/门牌确实要出字）：去掉「绝对不要任何文字」条款，只留
      「乱码 / 错字 / 糊字 / 重影」（NEG_TEXT_BAN）——否则正负自相矛盾，模型两头挨骂。
    两种分支都保留 NEG_WATERMARK（版权水印与画面文字是两回事，永远不要）。
    """
    parts = [NEG_QUALITY, NEG_MORPH]
    parts.append(NEG_TEXT_BAN if want_text else NEG_TEXT_BAN + ", " + NEG_NO_TEXT)
    parts.append(NEG_WATERMARK)
    return ", ".join(p for p in parts if p)


__all__ = [
    "SECTIONS", "SECTION_LABELS_CN", "STYLE_PRESETS", "STYLE_ALIASES_CN",
    "CAMERA_PRESETS", "CAMERA_ALIASES_CN", "AUDIO_SPEECH_PRESET", "AUDIO_AMBIENT_PRESET",
    "NEG_QUALITY", "NEG_MORPH", "NEG_TEXT_BAN", "NEG_NO_TEXT", "NEG_WATERMARK",
    "TEXT_INSTRUCTION_TERMS", "TEXT_CONTENT_TERMS",
    "has_text_instruction", "sanitize_positive", "text_instruction_clauses", "contains_cjk",
    "style_text", "camera_text", "prompt_sections", "build_prompt", "negative_prompt",
]
