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
    assert added == ["positive:speech", "negative:audio"]


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
