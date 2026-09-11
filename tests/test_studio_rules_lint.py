#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio.rules.lint 单测：创空间剧本静态预检（搬 runs/h3/story_lint + IP 词表 + 素材授权）。

覆盖三类：
  · 移植规则（引号 / cast / speaker / 越界 / 时长 / 动作堆叠 / 中文文本 / 禁字矛盾 / 角色卡）；
  · 创空间新增规则（版权 IP 词表 → error；素材授权 → warning）；
  · 契约（lint_story 的四个键、summary 文本、error ↔ ok 的对应关系、纯标准库）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.rules import lint as L  # noqa: E402


def _story(**kw):
    """一份"照做就能拍"的最小合规剧本（改一个字段就能造出对应缺陷）。"""
    s = {
        "title": "the last radio",
        "style": "cinematic, 35mm, natural light",
        "characters": {
            "A": "a middle-aged repairman in a worn jacket",
            "B": "a young woman with short hair",
        },
        "segments": [
            {"cast": ["A"], "prompt": "wide shot of a repair shop at dawn", "seconds": 8},
            {"cast": ["A", "B"], "prompt": "two-shot on a wooden bench", "seconds": 8},
        ],
        "lines": {
            "0": {"text": "it still works.", "speaker": "A"},
            "1": {"text": "keep it then.", "speaker": "B"},
        },
        "seconds": 4,
    }
    s.update(kw)
    return s


# ── 正例：全合规 ────────────────────────────────────────────────────────────

def test_clean_story_passes_and_report_contract():
    """全合规剧本：errors/warnings 都空、ok=True，且返回体就是约定的四个键。"""
    rep = L.lint_story(_story())
    assert rep["errors"] == [] and rep["warnings"] == []
    assert rep["ok"] is True
    assert rep["summary"] == "LINT_SUMMARY: errors=0 warnings=0"
    assert sorted(rep) == ["errors", "ok", "summary", "warnings"]
    # 兼容壳：老调用点用的 (errors, warnings) 元组
    assert L.lint(_story()) == ([], [])


def test_committed_spark_stories_still_pass_the_port():
    """搬过来的规则不能比 spark 更严：spark 已提交的剧本必须仍然 0 error（回归闸门）。"""
    for name in ("story_template.json", "story_radio.json"):
        p = ROOT / "config" / name
        if not p.is_file():
            continue
        rep = L.lint_story(json.loads(p.read_text(encoding="utf-8-sig")))
        assert rep["errors"] == [], (name, rep["errors"])
        assert rep["ok"] is True


# ── 移植规则：error ─────────────────────────────────────────────────────────

def test_quoted_dialogue_in_prompt_is_an_error():
    """引号 = 模型画字幕的开关 → 必须 error（历史事故：成片两条叠字）。"""
    s = _story()
    s["segments"][1]["prompt"] = 'the father says: "this radio, i fixed it myself."'
    rep = L.lint_story(s)
    assert rep["ok"] is False
    assert any("引号" in e for e in rep["errors"])


def test_cast_must_exist_in_characters():
    """cast 里写了角色卡没有的人 → 人物形象卡注入失败、脸会漂。"""
    s = _story()
    s["segments"][0]["cast"] = ["C"]
    rep = L.lint_story(s)
    assert rep["ok"] is False
    assert any("不在 characters" in e for e in rep["errors"])


def test_line_needs_speaker_when_multiple_cast():
    """多角色镜头不写 speaker → 不知道谁在说；单人镜头可以省略。"""
    s = _story()
    s["lines"]["1"] = {"text": "keep it then."}
    assert any("speaker" in e for e in L.lint_story(s)["errors"])
    s2 = _story()
    s2["segments"][1]["cast"] = ["B"]
    s2["lines"]["1"] = {"text": "keep it then."}
    assert not any("speaker" in e for e in L.lint_story(s2)["errors"])


def test_line_index_out_of_range_is_an_error():
    s = _story()
    s["lines"]["9"] = {"text": "out of range", "speaker": "A"}
    rep = L.lint_story(s)
    assert rep["ok"] is False
    assert any("越界" in e for e in rep["errors"])


def test_missing_title_and_empty_segments_are_errors():
    """结构缺失也必须是 error；且此时合规扫描仍要继续（早退不能吞掉 IP 命中）。"""
    s = _story(title="   ", segments=[], style="star wars style")
    rep = L.lint_story(s)
    assert rep["ok"] is False
    assert any("缺 title" in e for e in rep["errors"])
    assert any("segments" in e for e in rep["errors"])
    assert any("版权" in e for e in rep["errors"])


def test_non_dict_story_is_an_error():
    """剧本直接来自访客输入 → 不是 dict 也不能抛异常把接口打挂。"""
    for bad in (None, "not a story", [1, 2]):
        rep = L.lint_story(bad)
        assert rep["ok"] is False and rep["errors"]


# ── 移植规则：warning（建议改，不改也能拍） ───────────────────────────────────

def test_long_line_is_a_warning_and_ok_stays_true():
    """台词太长而 seconds 太小 → 只说 warning（生成时会自动抬段长），不能拦着不让拍。"""
    s = _story()
    s["lines"]["1"] = {"text": "这是一句很长的台词" * 5, "speaker": "B"}
    rep = L.lint_story(s)
    assert rep["ok"] is True and rep["errors"] == []
    assert any("约需" in w for w in rep["warnings"])
    assert rep["summary"] == "LINT_SUMMARY: errors=0 warnings=1"


def test_chinese_instruction_text_warns_unless_sign_text_is_wanted():
    s = _story()
    s["segments"][0]["prompt"] = "close-up of the desk, 超高清摄影 矢量级笔画锐度"
    assert any("中文" in w for w in L.lint_story(s)["warnings"])
    s2 = _story()
    s2["segments"][0]["prompt"] = "a shop sign reads 修表 in Chinese characters"
    assert not any("中文" in w for w in L.lint_story(s2)["warnings"])


def test_action_pileup_and_text_ban_conflict_warn():
    s = _story()
    s["segments"][0]["prompt"] = "he walks in, then sits, then opens the box, then smiles"
    assert any("动作太多" in w for w in L.lint_story(s)["warnings"])
    s2 = _story(style="cinematic, no on-screen text, no lettering")
    s2["segments"][0]["prompt"] = "a shop sign reads CLOSED in the window"
    assert any("自相矛盾" in w for w in L.lint_story(s2)["warnings"])


def test_missing_character_cards_warn():
    s = _story(characters={},
               segments=[{"prompt": "empty street at dawn", "seconds": 8}],
               lines={})
    rep = L.lint_story(s)
    assert rep["errors"] == [] and rep["ok"] is True
    assert any("角色卡" in w for w in rep["warnings"])


# ── 新增规则 (a)：版权/IP 词表 → error ──────────────────────────────────────

def test_ip_proper_noun_is_an_error_with_rewrite_advice():
    """英文 IP 角色名命中 → error，并且必须给出「改写为原创设定」的建议。"""
    s = _story()
    s["segments"][0]["prompt"] = "a stormtrooper patrols the hangar bay"
    rep = L.lint_story(s)
    assert rep["ok"] is False
    hit = [e for e in rep["errors"] if "stormtrooper" in e]
    assert hit and "原创" in hit[0] and "版权" in hit[0]


def test_chinese_ip_terms_are_caught_too():
    """中文 IP 词（星球大战 / 风暴兵 / 绝地 / 黑客帝国）同样必须拦下。"""
    for term in ("风暴兵", "绝地武士", "黑客帝国", "米老鼠"):
        s = _story()
        s["segments"][0]["prompt"] = "an empty corridor with a %s poster" % term
        rep = L.lint_story(s)
        assert rep["ok"] is False, term
        assert any(term in e and "原创" in e for e in rep["errors"]), (term, rep["errors"])


def test_ip_hit_anywhere_in_the_story_text_is_scanned():
    """标题 / 风格 / 角色卡 / 台词都在扫描范围内（不只看 prompt）。"""
    s = _story(title="a jedi story")
    assert any("jedi" in e.lower() for e in L.lint_story(s)["errors"])
    s2 = _story(characters={"A": "a darth vader lookalike", "B": "a young woman"})
    assert any("darth" in e for e in L.lint_story(s2)["errors"])
    s3 = _story()
    s3["lines"]["0"] = {"text": "may the force be with you", "speaker": "A"}
    assert any("原创" in e for e in L.lint_story(s3)["errors"])


def test_ambiguous_ip_words_only_warn_and_longest_match_wins():
    """HAL / 2001 这类词既是 IP、也是普通词 → 只告警；与强词条重叠时不重复报。"""
    s = _story()
    s["segments"][0]["prompt"] = "a quiet lab in 2001"
    rep = L.lint_story(s)
    assert rep["ok"] is True and rep["errors"] == []
    assert any("2001" in w and "疑似 IP" in w for w in rep["warnings"])

    s2 = _story()
    s2["segments"][0]["prompt"] = "the computer HAL 9000 speaks softly"
    rep2 = L.lint_story(s2)
    assert rep2["ok"] is False
    assert any("hal 9000" in e for e in rep2["errors"])
    assert not any("疑似 IP 名词 'hal'" in w for w in rep2["warnings"])


# ── 新增规则 (b)：素材授权 → warning ────────────────────────────────────────

def test_assets_without_license_marker_warn():
    """声明了参考素材却没有授权标记 → warning；标了 assets_licensed 就不再告警。"""
    s = _story()
    s["assets"] = ["refs/face_a.png", "refs/costume.png"]
    rep = L.lint_story(s)
    assert rep["ok"] is True and rep["errors"] == []
    assert any("授权" in w and "assets" in w for w in rep["warnings"])

    s["assets_licensed"] = True
    assert not any("授权" in w for w in L.lint_story(s)["warnings"])


def test_segment_level_reference_image_also_needs_license():
    """段级参考图（首帧/参考图）也算素材：只声明不讲授权同样告警。"""
    s = _story()
    s["segments"][0]["ref_image"] = "refs/first_frame.png"
    rep = L.lint_story(s)
    assert rep["ok"] is True
    assert any("seg0.ref_image" in w and "授权" in w for w in rep["warnings"])


# ── 创空间硬约束：纯标准库 ──────────────────────────────────────────────────

def test_module_is_pure_stdlib_without_project_imports():
    """创空间约束：不 import 项目内其它模块、不联网（源码里只应出现 re / __future__）。"""
    src = Path(L.__file__).read_text(encoding="utf-8")
    mods = set(re.findall(r'^(?:from|import)\s+([\w\.]+)', src, re.M))  # 只看顶格的 import
    assert mods <= {"re", "__future__"}, mods
