#!/usr/bin/env python3
"""语音条款默认注入层单测（2026-09-10 用户要求：把语音相关提示词写进默认设置）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import prompts as P  # noqa: E402


def test_detect_speech_wanted():
    assert P.detect_speech_wanted("a cat by the window", "", "r2v") is False
    assert P.detect_speech_wanted("the father says: hello", "", "i2v") is True
    assert P.detect_speech_wanted("他在说话，台词很清楚", "", "t2v") is True
    assert P.detect_speech_wanted("empty scenery", "你好", "t2v") is True      # 有 TTS 文本
    assert P.detect_speech_wanted("empty scenery", "", "talk") is True          # 说话类阶段


def test_augment_speech_clause_injects_both_sides():
    pos, neg, added = P.augment_speech_clause("cinematic shot", "low quality", True)
    assert "clear articulate speech" in pos and "cinematic shot" in pos
    assert "mumbled speech" in neg and "low quality" in neg
    assert added == ["positive:speech", "positive:no-text", "negative:audio", "negative:no-text"]


def test_default_is_no_on_screen_text_for_dialogue():
    """用户定案：字幕由后期烧录 → 台词段必须让模型**不要画任何字**。"""
    pos, neg, _ = P.augment_speech_clause("the father says: hello", "", True)
    assert "no subtitles, no captions" in pos
    assert "burned-in captions" in neg and "on-screen subtitles" in neg
    # 无台词段不加（避免反向诱导），但仍保留环境声条款
    pos2, _, _ = P.augment_speech_clause("empty street, rain", "", False)
    assert "ambient sound only" in pos2 and "no subtitles" not in pos2


def test_four_dimension_text_spec_when_text_is_wanted():
    """明确要画面内文字时（招牌/字样）：中文前缀 + 字体风格/字号层级/颜色对比/动态行为 四维 + 禁艺术化手写。"""
    pos, neg, added = P.augment_speech_clause(
        "a shop sign reads: 修表 in Chinese characters", "", True)
    # 前缀已被移除：独立成句的风格字符串（中/英文都试过）会被 H3 画进画面
    assert "超高清摄影" not in pos and "ultra-high-definition photography," not in pos
    assert "vector-grade stroke sharpness" in pos      # 清晰度要求已并入长描述句
    for dim in ("(1) font style", "(2) size hierarchy", "(3) colour contrast", "(4) motion"):
        assert dim in pos
    assert "artistic lettering" in neg and "calligraphy" in neg
    assert "positive:text-4d" in added and "positive:text-prefix" not in added
    assert P.detect_text_wanted('a shop sign reads: "修表"') is True
    assert P.detect_text_wanted("招牌上写着“修表”两个字") is True
    assert P.detect_text_wanted("the father speaks slowly") is False
    # 反向句不能误判（"no signage text" / "no lettering on any surface" 都不得触发文字条款）
    assert P.detect_text_wanted("no lettering on any surface, no signage text") is False


def test_augment_no_speech_segment_gets_ambient_only():
    pos, _, added = P.augment_speech_clause("empty room, rain", "", False)
    assert "ambient sound only" in pos and "positive:no-speech" in added


def test_augment_is_idempotent_and_switchable():
    once = P.augment_speech_clause("shot", "low quality", True)
    twice = P.augment_speech_clause(once[0], once[1], True)
    assert twice[0] == once[0] and twice[1] == once[1]
    assert twice[2] == []
    off = P.augment_speech_clause("shot", "low quality", True, enabled=False)
    assert off == ("shot", "low quality", [])


def test_spoken_line_clause_avoids_quotes_to_suppress_h3_subtitles():
    """实测：引号会让 H3 把台词画成画面字幕；条款必须"无引号 + audio only"（2026-09-10）。"""
    from runs.h3 import story_film as sf

    clause = sf.spoken_line_clause({"text": "这台收音机，我修了三个晚上。", "speaker": "父亲"}, ["父亲"])
    assert "这台收音机，我修了三个晚上。" in clause          # 汉字原文必须保留（保发音）
    assert '"' not in clause and "“" not in clause            # 不能有引号（否则模型会画字幕）
    assert "audio only" in clause and "never appear as written text" in clause
    assert "父亲 speaks Mandarin Chinese" in clause


def test_mix_filtergraph_loudnorm_comes_after_amix():
    """回归：loudnorm 必须在 amix 之后，否则音轨被截短 3 秒（成片尾部静音）。"""
    from runs.h3.film_stitch import mix_filtergraph

    fc = mix_filtergraph(864, 480, 24)
    assert fc.index("amix=") < fc.index("loudnorm="), "loudnorm 不能排在 amix 之前"
    assert "asetpts=N/SR/TB" in fc                     # 混音后重置时间戳
    assert "[am]asetpts=N/SR/TB," in fc              # 时间戳重置后再进清晰链/响度
    assert "scale=864:480" in fc and "fps=24" in fc


def test_ambience_source_room_and_rain():
    """无台词段铺房间底噪（用户定案）：波形/电平/淡入淡出都要对，且默认远低于语音。"""
    from runs.h3.film_stitch import ambience_source

    room = ambience_source("room", -32.0, 4.5)
    assert "anoisesrc=color=brown" in room and "lowpass=f=900" in room
    assert "volume=-32.0dB" in room and "duration=4.500" in room
    assert "afade=t=in" in room and "afade=t=out" in room
    assert "aformat=channel_layouts=stereo" in room

    rain = ambience_source("rain", -30.0, 3.0)
    assert "anoisesrc=color=pink" in rain and "highpass=f=400" in rain and "volume=-30.0dB" in rain

    assert ambience_source("none", -32.0, 4.0) == ""
    assert ambience_source("", -32.0, 4.0) == ""
    # 极短段也不能出现负的淡出起点
    assert "afade=t=out:st=0.100" in ambience_source("room", -32.0, 0.2)


def test_template_patcher_is_idempotent(tmp_path):
    """模板默认提示词补丁：写入一次即生效，重复跑不再叠加（用户要求写进工作流默认设置）。"""
    import json
    from runs.h3 import template_defaults as td

    doc = {"nodes": [
        {"id": 20, "type": "PrimitiveStringMultiline",
         "widgets_values": ["Bold comic-book ink style, night city"]},
        {"id": 18, "type": "MiniMaxH3ReferenceToVideo",
         "widgets_values": ["", 1344, 768, 124, "match"]},          # 非提示词节点不应被动
    ]}
    p = tmp_path / "video_minimax_h3_t2v.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    first = td.patch_file(p, apply=True)
    assert first["patched"] == 1
    second = td.patch_file(p, apply=True)
    assert second["patched"] == 0 and second["already"] == 1
    txt = p.read_text(encoding="utf-8")
    assert txt.count("clear articulate speech") == 1
    assert "MiniMaxH3ReferenceToVideo" in txt and "1344" in txt


def test_committed_templates_already_carry_the_clause():
    import io
    import json
    for name in ("video_minimax_h3_t2v", "video_minimax_h3_i2v", "video_minimax_h3_r2v"):
        doc = json.load(io.open(ROOT / "config" / "templates" / (name + ".json"), encoding="utf-8-sig"))
        assert "clear articulate speech" in json.dumps(doc, ensure_ascii=False), name


def test_default_prompt_files_carry_the_clause():
    """用户要求：条款必须在工作流默认提示词文件里就有（不依赖 agent 临场写）。"""
    pos = (ROOT / "prompts" / "positive_prompts.txt").read_text(encoding="utf-8")
    neg = (ROOT / "prompts" / "negative_prompts.txt").read_text(encoding="utf-8")
    assert "clear articulate speech" in pos
    assert "mumbled speech" in neg and "garbled unintelligible voice" in neg
