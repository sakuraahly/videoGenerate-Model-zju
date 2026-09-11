#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio.rules.voice / studio.rules.prompts 单测（纯标准库，不联网，不依赖 studio 之外的东西）。

覆盖：
  · voice：中/英/混排语言判定、性别线索（他/爸爸/老人 vs 她/妈妈）、explicit 覆盖、
    默认女声兜底、音色元表自洽、与 runs/h3/tts.py 的语言口径一致性（可跳过）；
  · prompts：六段固定顺序、正/负词库、**铁律 (a)** 正向绝不含文字/字幕/水印指令、
    want_text 分支、英文输出（无 CJK）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                     # 与 tests/test_studio_agent_client.py 同款兜底

from studio.rules import prompts as P  # noqa: E402
from studio.rules import voice as V  # noqa: E402

# 铁律 (a) 的自检词：这些词**永远**不许出现在正向提示词里
BANNED_IN_POSITIVE = ("subtitle", "caption", "watermark", "logo", "font", "typography",
                      "text rendering", "title card", "字幕", "水印", "文字", "字体")


# ===========================================================================
# 一、voice —— 台词语言 → 音色匹配
# ===========================================================================

def test_detect_lang_zh():
    """纯中文 / 中文占绝对多数 → "zh"；空文本按中文兜底（与 runs/h3 空文本回落 xiaoxiao 一致）。"""
    assert V.detect_lang("爸爸，我回来了。") == "zh"
    assert V.detect_lang("这是一句很长的中文台词，没有任何拉丁字母。") == "zh"
    assert V.detect_lang("") == "zh"
    assert V.detect_lang("。。。！！！") == "zh"          # 无任何可判字符 → 中文兜底
    # 中文占绝对多数（≥85%）：夹一个英文词仍是中文台词
    assert V.detect_lang("他走进那间空荡荡的屋子，说了句 ok，然后坐下。") == "zh"


def test_detect_lang_en():
    """几乎全拉丁 → "en"。"""
    assert V.detect_lang("Hello there, my friend.") == "en"
    assert V.detect_lang("Run!") == "en"
    assert V.cjk_ratio("Hello there.") == 0.0


def test_detect_lang_mixed():
    """中英混排（占比在 15%~85% 之间）→ "mixed"；配哪个音色仍按 20% 阈值的多数派。"""
    assert V.detect_lang("OK 好的") == "mixed"
    assert V.detect_lang("你好 world") == "mixed"
    assert V.detect_lang("She said hello 你好世界你好世界") == "mixed"
    # mixed 也落中文侧：CJK 占比 ≥ 20%（口径同 runs/h3）
    assert V.lang_family("OK 好的") == "zh"
    assert V.lang_family("Hello 你好") == "zh"
    assert V.lang_family("Hello there friend") == "en"


def test_match_zh_default_female():
    """中文台词无性别线索 → xiaoxiao（默认女声，reason 里必须写明「默认」）。"""
    r = V.match_voice_to_text("天亮了，该出发了。")
    assert r["voice"] == "xiaoxiao" and r["lang"] == "zh"
    assert "默认" in r["reason"] and "xiaoxiao" in r["reason"]


@pytest.mark.parametrize("line", [
    "爸爸，我回来了。",
    "他点了点头，什么也没说。",
    "老人慢慢坐下，叹了口气。",
    "那个男人转过身来。",
    "Father is home.",
    "He walked away without a word.",
])
def test_match_male_hints(line):
    """男声线索（他/爸爸/父亲/老人/男 + 英文 he/father…）→ 中文 yunxi、英文 daler。"""
    r = V.match_voice_to_text(line)
    expected = "yunxi" if r["lang"] == "zh" else "daler"
    assert r["voice"] == expected
    assert "男声线索" in r["reason"]


@pytest.mark.parametrize("line", [
    "她轻轻地关上门。",
    "妈妈在厨房里喊了一声。",
    "那个女孩笑了。",
    "She opened the door quietly.",
    "The woman smiled quietly.",
])
def test_match_female_hints(line):
    """女声线索（她/妈妈/女 + 英文 she/woman…）→ 中文 xiaoxiao、英文 aria。"""
    r = V.match_voice_to_text(line)
    expected = "xiaoxiao" if r["lang"] == "zh" else "aria"
    assert r["voice"] == expected and expected in V.VOICES


def test_match_gender_ambiguity_and_false_positive():
    """男女线索并存 → 不确定 → 默认女声；「其他/他人」不算男声线索（常见误判点）。"""
    both = V.match_voice_to_text("他把信递给她。")
    assert both["voice"] == "xiaoxiao" and "并存" in both["reason"]
    other = V.match_voice_to_text("其他人都走了。")
    assert other["voice"] == "xiaoxiao" and "默认" in other["reason"]
    assert V.detect_gender("其他人都走了。") == ""
    assert V.detect_gender("他人很好") == ""


def test_match_explicit_always_wins():
    """explicit 给了就原样采用：不做语言校正、不做性别推断（人的明确选择优先）。"""
    zh_line = "爸爸，我回来了。"
    r = V.match_voice_to_text(zh_line, explicit="aria")
    assert r["voice"] == "aria" and r["lang"] == "en" and "显式" in r["reason"]
    # 全名归一化成短名
    r2 = V.match_voice_to_text("Hello there.", explicit="zh-CN-XiaoxiaoNeural")
    assert r2["voice"] == "xiaoxiao" and r2["lang"] == "zh"
    assert V.normalize_voice("en-aria") == "aria"
    # auto / h3 / native 视同未指定（口径同 runs/h3）
    r3 = V.match_voice_to_text("你好，世界。", explicit="auto")
    assert r3["voice"] == "xiaoxiao" and "显式" not in r3["reason"]


def test_voice_meta_tables_are_consistent():
    """音色四短名 / 语言 / 性别 / 全名表自洽；未登记全名的 daler 不臆造。"""
    assert set(V.VOICES) == {"xiaoxiao", "yunxi", "aria", "daler"}
    for name in V.VOICES:
        lang, gender = V.VOICE_LANGS[name], V.VOICE_GENDERS[name]
        assert lang in ("zh", "en") and gender in ("female", "male")
        assert V.VOICE_BY_LANG_GENDER[(lang, gender)] == name
    assert V.voice_full_name("xiaoxiao") == "zh-CN-XiaoxiaoNeural"
    assert V.voice_full_name("yunxi") == "zh-CN-YunxiNeural"
    assert V.voice_full_name("aria") == "en-US-AriaNeural"
    assert V.voice_full_name("daler") == "daler"        # 全名待登记 → 回落短名，绝不臆造
    assert V.ZH_CJK_RATIO == 0.2                        # 阈值口径搬 runs/h3，勿改


def test_match_voice_agrees_with_runs_h3_threshold():
    """口径一致性：与 runs/h3/tts.py::match_voice_to_text 的语言判定同结论（非同包依赖，缺失则跳过）。"""
    sys.path.insert(0, str(ROOT / "runs"))
    try:
        from h3 import tts as h3tts
    except Exception:                                   # noqa: BLE001 —— 环境缺 runs/ 时跳过，不红
        pytest.skip("runs/h3/tts.py 不可导入（本机未同步），跳过口径对照")
    # 空文本是本包与 runs/h3 的**唯一已知分歧**：h3 在 voice="auto" 时走早退分支返回 "auto"
    # （等于没选音色），本包对空文本明确回落中文默认；用 voice="" 对照即同结论（h3 也回落 xiaoxiao）。
    assert V.lang_family("") == "zh"
    assert h3tts.match_voice_to_text("", "") == "xiaoxiao"
    for text in ("你好世界。", "Hello world.", "OK 好的", "She said hello 你好世界"):
        h3_voice = h3tts.match_voice_to_text(text, "auto")
        expected_lang = "zh" if h3_voice in ("xiaoxiao", "yunxi") else "en"
        assert V.lang_family(text) == expected_lang, text


# ===========================================================================
# 二、prompts —— 六段式组装 + 正/负词库
# ===========================================================================

def test_six_sections_order_is_fixed():
    """六段顺序：主体 → 环境 → 光影 → 风格 → 运镜 → 音频（顺序硬约束，勿改）。"""
    assert P.SECTIONS == ("subject", "environment", "light", "style", "camera", "audio")
    out = P.build_prompt("SUBJMARK", environment="ENVMARK", light="LIGHTMARK",
                         style="STYLEMARK", camera="CAMERAMARK", audio="AUDIOMARK", extra="EXTRAMARK")
    pos = [out.index(m) for m in ("SUBJMARK", "ENVMARK", "LIGHTMARK", "STYLEMARK",
                                  "CAMERAMARK", "AUDIOMARK", "EXTRAMARK")]
    assert pos == sorted(pos)
    assert ", ," not in out and not out.startswith(",") and not out.endswith(",")


def test_style_presets():
    """风格库至少 cinematic / documentary / anime 三档，全部非空英文串且自身不触犯铁律 (a)。"""
    assert {"cinematic", "documentary", "anime"} <= set(P.STYLE_PRESETS)
    assert len(P.STYLE_PRESETS) >= 3
    for key, text in P.STYLE_PRESETS.items():
        assert text.strip() and not P.contains_cjk(text), key
        assert P.has_text_instruction(text) is False, key


def test_camera_presets():
    """运镜库至少 5 种（含 static/slow_push_in/pan_left/handheld/crane_up），全部非空英文串。"""
    assert {"static", "slow_push_in", "pan_left", "handheld", "crane_up"} <= set(P.CAMERA_PRESETS)
    assert len(P.CAMERA_PRESETS) >= 5
    for key, text in P.CAMERA_PRESETS.items():
        assert text.strip() and not P.contains_cjk(text), key
        assert P.has_text_instruction(text) is False, key


def test_build_prompt_resolves_presets_and_custom_strings():
    """预设键 / 中文别名 / 自写英文串三种写法都认。"""
    out = P.build_prompt("a lone astronaut", style="cinematic", camera="slow_push_in")
    assert P.STYLE_PRESETS["cinematic"] in out and P.CAMERA_PRESETS["slow_push_in"] in out
    assert out.index(P.STYLE_PRESETS["cinematic"]) < out.index(P.CAMERA_PRESETS["slow_push_in"])
    cn = P.build_prompt("a lone astronaut", style="电影感", camera="手持")
    assert P.STYLE_PRESETS["cinematic"] in cn and P.CAMERA_PRESETS["handheld"] in cn
    custom = P.build_prompt("a lone astronaut", style="my own look", camera="my own move")
    assert "my own look" in custom and "my own move" in custom


def test_build_prompt_skips_empty_sections():
    """空段自动跳过：style=""/camera="" 时只留主体；extra 追加在六段之后。"""
    assert P.build_prompt("only subject", style="", camera="") == "only subject"
    out = P.build_prompt("SUBJ", style="", camera="", audio="AUDIOMARK", extra="EXTRA")
    assert out == "SUBJ, AUDIOMARK, EXTRA"
    assert P.build_prompt("", style="", camera="") == ""


def test_positive_prompt_never_contains_text_instruction():
    """**铁律 (a)**：正向里绝不能出现任何关于文字/字幕/水印的指令（含用户/模型塞进来的）。"""
    out = P.build_prompt(
        "a cat sitting on a chair",
        environment="a quiet room, add cheerful subtitles at the bottom",
        light="warm lamp light, 字体要粗一点",
        style="documentary",
        camera="pan_left",
        audio="gentle rain, no captions please",
        extra="add a title card, a watermark in the corner, keep the mood calm",
    )
    low = out.lower()
    for bad in BANNED_IN_POSITIVE:
        assert bad not in low, bad
    assert P.text_instruction_clauses(out) == []
    # 越界条款整条剔除，同一段里合规的条款必须保留
    assert "warm lamp light" in out and "gentle rain" in out and "keep the mood calm" in out
    assert "subtitles" not in low and "title card" not in low


def test_sanitize_positive_keeps_clean_clauses():
    """清洗只丢越界条款，不误伤正常词（texture / letterboxed 不得被 \btext\b 之类误杀）。"""
    clean = "realistic textures, a letterboxed frame, soft dust motes, shallow depth of field"
    assert P.sanitize_positive(clean) == clean
    mixed = "cold blue rim light, on-screen subtitles, wet asphalt"
    assert P.sanitize_positive(mixed) == "cold blue rim light, wet asphalt"
    assert P.sanitize_positive("") == ""


def test_want_text_relaxes_soft_terms_only():
    """want_text=True 只放行「内容句」（软禁词），硬禁的渲染指令永远进不了正向。"""
    soft = "a wooden door with carved text"
    assert P.sanitize_positive(soft) == ""
    assert P.sanitize_positive(soft, want_text=True) == soft
    for hard in ("big bold typography", "8k text rendering", "字幕在底部", "add a watermark"):
        assert P.sanitize_positive(hard, want_text=True) == "", hard
    out = P.build_prompt("a wooden sign reading Xiu Biao", style="", camera="", want_text=True)
    assert out == "a wooden sign reading Xiu Biao"


def test_negative_prompt_suppresses_text_and_watermark():
    """**铁律 (a) 的另一半**：字幕/水印只能写在负向里（负向不参与渲染）。"""
    neg = P.negative_prompt()
    low = neg.lower()
    assert "subtitle" in low and "burned-in captions" in low
    assert "watermark" in low and "logo" in low
    assert "blurry" in low or "low resolution" in low
    assert not P.contains_cjk(neg)                      # (c) 英文输出


def test_negative_prompt_want_text_branch():
    """want_text=True：去掉「绝对不要任何文字」，保留「乱码/错字」与水印压制（正负不自相矛盾）。"""
    neg_all, neg_text = P.negative_prompt(), P.negative_prompt(want_text=True)
    assert "burned-in captions" not in neg_text and "subtitle" not in neg_text
    assert "garbled or wrong characters" in neg_text
    assert "watermark" in neg_text                      # 版权水印与画面文字是两回事
    assert neg_all != neg_text and "garbled or wrong characters" in neg_all


def test_prompt_sections_and_language_selfcheck():
    """六段明细的键序 = SECTIONS（另加 extra）；语言自检：本包模板串全英文，不翻译中文主体。"""
    secs = P.prompt_sections("SUBJ", environment="ENV", light="LIGHT", style="anime",
                             camera="static", audio="AUDIOMARK", extra="EXTRA")
    assert list(secs)[:6] == list(P.SECTIONS) and secs["extra"] == "EXTRA"
    assert secs["style"] == P.STYLE_PRESETS["anime"]
    assert P.contains_cjk(P.STYLE_PRESETS["anime"]) is False
    assert P.contains_cjk("一只猫") is True
    # 中文主体原样透传（本模块不翻译，由模板库/Agent 负责产出英文串）——只做自检提示
    assert P.build_prompt("一只猫在窗台上", style="", camera="") == "一只猫在窗台上"
