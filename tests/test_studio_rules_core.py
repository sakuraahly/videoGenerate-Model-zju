#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio/rules 规则引擎单测：frames（帧网格/参数推导）+ templates（分镜骨架库）。

对应 book-20 §7 P0 验收②：零 key 状态下产出的分镜表要"照做就能拍"。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.rules import frames as fr  # noqa: E402
from studio.rules import templates as tp  # noqa: E402


# ---------------------------------------------------------------- frames
def test_frame_grid_is_5_plus_17k():
    assert fr.frame_grid(130)[:8] == [5, 22, 39, 56, 73, 90, 107, 124]


def test_frames_for_seconds_5s_is_124():
    assert fr.frames_for_seconds(5.0) == 124        # 107 帧只有 4.458s，不够


def test_fit_frames_seconds_picks_smallest_covering_slot():
    # 台词 2.76s + 0.2s 余量 → 73 帧（3.042s），而不是 107 帧（4.458s）
    assert fr.fit_frames_seconds(2.76, margin=0.2) == round(73 / 24.0, 3)


def test_resolution_presets_and_fallback():
    assert fr.resolution_of("720p") == (1280, 736)
    assert fr.resolution_of("768p") == (1344, 768)
    assert fr.resolution_of("不存在") == (864, 480)


def test_estimate_speech_seconds_zh_and_en():
    zh = fr.estimate_speech_seconds("今天真困，早点休息吧。")
    en = fr.estimate_speech_seconds("we still have twelve minutes")
    assert 1.5 <= zh <= 5.0
    assert 0.6 <= en <= 4.0
    assert fr.estimate_speech_seconds("") >= 0.6


def test_allocate_segments_stays_on_grid_and_within_total():
    secs = fr.allocate_segments(30.0, 5)
    assert len(secs) == 5
    assert sum(secs) <= 30.0 + 0.05
    for s in secs:
        assert fr.frames_of(s) / 24.0 >= s - 1e-6      # 落网格且不短于请求


def test_allocate_segments_respects_min_segment():
    secs = fr.allocate_segments(1.0, 3, min_seg=2.0)
    assert len(secs) == 3 and all(s >= 2.0 for s in secs)


# ---------------------------------------------------------------- templates
def test_combo_count_meets_thickness_target():
    assert tp.combo_count() >= 50       # P0 厚度指标


def test_pick_motif_by_keywords():
    assert tp.pick_motif("最后一个人类在空城里按下总开关") == "last_human"
    assert tp.pick_motif("机器拒绝了返航指令") == "machine_refusal"
    assert tp.pick_motif("陪伴机器人永远同意你") == "gentle_cage"
    assert tp.pick_motif("望远镜先算出了那颗行星") == "cosmic_omen"


def test_pick_motif_is_deterministic_without_keyword():
    a = tp.pick_motif("今天天气不错", seed="s1")
    b = tp.pick_motif("今天天气不错", seed="s1")
    assert a == b and a in tp.MOTIFS


def test_build_storyboard_structure_is_complete():
    s = tp.build_storyboard("最后一个人类每天去按下整座城市的电源总开关",
                            style="cinematic", target_seconds=30, cast_mode="solo")
    for k in ("title", "style", "theme", "motif", "characters", "segments", "lines",
              "assets_licensed", "resolution", "total_seconds", "total_frames"):
        assert k in s, k
    assert len(s["segments"]) >= 3
    assert s["segments"][0]["frames"] in fr.frame_grid()
    for seg in s["segments"]:
        assert seg["prompt"].strip()
        assert seg["camera"].startswith("camera:")
        assert abs(seg["frames"] / 24.0 - seg["seconds"]) < 0.05


def test_talking_segment_keeps_line_out_of_visual_prompt():
    """台词铁律：台词原文进 lines/line，**不进画面提示词**。"""
    s = tp.build_storyboard("陪伴机器人永远同意你", target_seconds=30, cast_mode="solo")
    assert s["lines"], "应至少安排一句台词"
    line_text = s["lines"][0]["text"]
    for seg in s["segments"]:
        assert line_text not in seg["prompt"], "台词不得写进画面提示词"
    talking = [x for x in s["segments"] if x["line"]]
    assert talking and talking[0]["line"]["text"] == line_text


def test_positive_prompt_never_contains_on_screen_text_instruction():
    """正向提示词里绝不能有"文字/字幕/水印"类指令（会被模型画进画面）。"""
    s = tp.build_storyboard("机器拒绝了返航指令", style="anime", target_seconds=60, cast_mode="duo")
    banned = ["subtitle", "caption", "watermark", "on-screen text", "text overlay", "字幕", "水印"]
    for seg in s["segments"]:
        low = seg["prompt"].lower()
        for b in banned:
            assert b not in low, f"正向提示词出现禁用词 {b}: {seg['prompt'][:120]}"
        assert "no on-screen text" in seg["note"]


def test_anchor_injects_picture_tags_and_requires_license():
    s = tp.build_storyboard("空城里的最后一个人", anchor=True, target_seconds=20)
    assert "<Picture 1>" in s["segments"][0]["prompt"]
    assert s["assets_licensed"] is False        # 用了素材但未声明授权 → 触发 lint warning


def test_duo_cast_has_two_characters():
    s = tp.build_storyboard("温柔的牢笼", cast_mode="duo", target_seconds=45)
    assert len(s["characters"]) == 2
    assert len(s["segments"][0]["cast"]) == 2


def test_list_templates_reports_combos():
    info = tp.list_templates()
    assert info["combos"] == tp.combo_count()
    assert len(info["motifs"]) == 6 and len(info["styles"]) == 3


def test_storyboard_passes_lint_when_available():
    """与 lint 模块的联调：规则引擎自产的分镜表必须能通过自家预检。"""
    lint = __import__("pytest").importorskip("studio.rules.lint")
    s = tp.build_storyboard("地球上最后一个人按下总开关", target_seconds=30)
    r = lint.lint_story(s)
    assert r["errors"] == [], f"自产剧本不该有 error: {r['errors']}"
