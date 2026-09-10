#!/usr/bin/env python3
"""story_lint 单测：剧本预检规则（agent 写剧本前的 0 成本闸门）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import story_lint as L  # noqa: E402


def _story(**kw):
    s = {
        "title": "t", "style": "cinematic", "characters": {"A": "man", "B": "woman"},
        "segments": [{"cast": ["A"], "prompt": "shot one"}, {"cast": ["A", "B"], "prompt": "shot two"}],
        "lines": {"1": {"text": "你好", "speaker": "A"}}, "seconds": 4,
    }
    s.update(kw)
    return s


def test_frame_qa_retries_on_429(monkeypatch, tmp_path):
    """免费额度限流(429)必须退避重试，否则闸门会误判 unknown（实测连发多帧就撞限流）。"""
    import urllib.error
    from runs.h3 import frame_qa as Q

    state = {"n": 0}

    def fake_once(*a, **k):
        state["n"] += 1
        if state["n"] < 3:
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        return "NO"

    sleeps = []
    monkeypatch.setattr(Q, "_ask_once", fake_once)
    monkeypatch.setattr(Q.time, "sleep", lambda s: sleeps.append(s))
    img = tmp_path / "x.jpg"
    img.write_bytes(b"x")
    assert Q.ask_vlm(str(img), "q", "m", "b", "t") == "NO"
    assert state["n"] == 3 and len(sleeps) == 2


def test_quotes_in_prompt_are_an_error():
    """引号 = H3 画字幕的开关 → 必须是错误（历史事故：成片两条叠字）。"""
    s = _story()
    s["segments"][1]["prompt"] = 'the father says: "这台收音机，我修了三个晚上。"'
    err, _ = L.lint(s)
    assert any("引号" in e for e in err)


def test_cast_must_exist_in_characters():
    s = _story()
    s["segments"][0]["cast"] = ["不存在的角色"]
    err, _ = L.lint(s)
    assert any("不在 characters" in e for e in err)


def test_line_needs_speaker_when_multiple_cast():
    s = _story()
    s["lines"]["1"] = {"text": "你好"}
    err, _ = L.lint(s)
    assert any("speaker" in e for e in err)
    # 单人镜头可以省略 speaker
    s["lines"]["1"] = {"text": "你好"}
    s["segments"][1]["cast"] = ["A"]
    err2, _ = L.lint(s)
    assert not any("speaker" in e for e in err2)


def test_line_index_out_of_range():
    s = _story()
    s["lines"]["9"] = {"text": "越界", "speaker": "A"}
    err, _ = L.lint(s)
    assert any("越界" in e for e in err)


def test_long_line_warns_about_duration():
    s = _story()
    s["lines"]["1"] = {"text": "这是一句非常长的台词" * 4, "speaker": "A"}
    _, warn = L.lint(s)
    assert any("约需" in w for w in warn)


def test_story_new_writes_and_lints(tmp_path, monkeypatch, capsys):
    """agent 没有写文件工具 → 剧本落盘通道是 story_new（base64 传 JSON，避开引号）。"""
    import base64
    from runs.h3 import story_new as S

    monkeypatch.setattr(S, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    payload = base64.b64encode(json.dumps(_story(), ensure_ascii=False).encode()).decode()
    assert S.main(["--name", "demo", "--b64", payload]) == 0
    out = capsys.readouterr().out
    assert "STORY_NEW_OK" in out and "LINT_SUMMARY: errors=0" in out
    assert (tmp_path / "config" / "story_demo.json").is_file()
    bad = _story()
    bad["segments"][1]["prompt"] = 'x says: "hello"'
    p2 = base64.b64encode(json.dumps(bad, ensure_ascii=False).encode()).decode()
    assert S.main(["--name", "bad", "--b64", p2]) == 1
    assert "LINT_ERROR" in capsys.readouterr().out
    assert S.main(["--name", "x", "--json", "{not json"]) == 2


def test_too_many_actions_warns():
    s = _story()
    s["segments"][0]["prompt"] = "he walks in, then sits, then opens the box, then smiles"
    _, warn = L.lint(s)
    assert any("动作太多" in w for w in warn)


def test_chinese_instruction_text_in_prompt_warns():
    """中文指令文本会被 H3 画进画面（实测"无抗锯齿失真"变成乱码叠字）→ 必须告警。"""
    s = _story()
    s["segments"][0]["prompt"] = "close-up of the desk, 超高清摄影 矢量级笔画锐度"
    _, warn = L.lint(s)
    assert any("中文" in w for w in warn)
    # 确实要画面文字时（招牌原文）不告警
    s["segments"][0]["prompt"] = 'a shop sign reads 修表 in Chinese characters'
    _, warn2 = L.lint(s)
    assert not any("中文" in w for w in warn2)


def test_prompt_asking_for_text_conflicts_with_style_ban():
    s = _story()
    s["style"] = "cinematic, no on-screen text, no lettering"
    s["segments"][0]["prompt"] = "a shop sign reads 修表 in the window"
    _, warn = L.lint(s)
    assert any("自相矛盾" in w for w in warn)


def test_cli_reports_summary_and_exit_code(tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_story(), ensure_ascii=False), encoding="utf-8")
    assert L.main([str(p)]) == 0
    assert "LINT_SUMMARY: errors=0" in capsys.readouterr().out
    bad = _story()
    bad["segments"][1]["prompt"] = 'she says: "hello"'
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert L.main([str(p)]) == 1
    assert "LINT_ERROR" in capsys.readouterr().out


def test_committed_template_and_story_pass_lint():
    for name in ("story_template.json", "story_radio.json"):
        data = json.loads((ROOT / "config" / name).read_text(encoding="utf-8-sig"))
        err, _ = L.lint(data)
        assert err == [], (name, err)
