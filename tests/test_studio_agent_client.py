#!/usr/bin/env python3
"""studio/agent_client 单测：工具集 + 外置大脑 + 接口协议（不联网，全部 mock）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))

import agent_client as ac  # noqa: E402
from app import agent_step, jobs_table  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "ENGINE_BASE_URL", "ENGINE_API_KEY",
              "ENGINE_STATUS_URL", "VIDEO_API_URL", "VIDEO_API_KEY", "VIDEO_API_STATUS_URL",
              "TOOLSET", "AGENT_SYSTEM_PROMPT", "AGENT_SYSTEM_PROMPT_FILE"):
        monkeypatch.delenv(k, raising=False)


def _client(**env):
    for k, v in env.items():
        import os
        os.environ[k] = v
    return ac.AgentClient()


def test_toolset_names_and_schema():
    names = [t["name"] for t in ac.TOOLS]
    assert names == ["generate_video", "generate_talk", "make_story_film", "answer"]
    for t in ac.TOOLS:
        assert t["description"] and isinstance(t["params"], dict)


def test_toolset_filtering():
    c = _client(TOOLSET="generate_talk,answer")
    assert [t["name"] for t in c.tools()] == ["generate_talk", "answer"]
    assert _client(TOOLSET="all").tools() == ac.TOOLS
    # 未开放的工具必须被拒绝(不让大脑越权调用)
    out = c.run_tool({"tool": "generate_video", "args": {"prompt": "x"}})
    assert out["ok"] is False and "TOOLSET" in out["text"]


def test_system_prompt_injection(tmp_path, monkeypatch):
    assert _client().system_prompt == ac.DEFAULT_SYSTEM
    f = tmp_path / "p.md"
    f.write_text("自定义系统提示:必须用中文回答。", encoding="utf-8")
    monkeypatch.setenv("AGENT_SYSTEM_PROMPT_FILE", str(f))
    assert _client().system_prompt.startswith("自定义系统提示")
    monkeypatch.setenv("AGENT_SYSTEM_PROMPT", "内联提示优先")
    assert _client().system_prompt == "内联提示优先"


@pytest.mark.parametrize("text,tool", [
    ("让老人说一句台词", "generate_talk"),
    ("做个 3 段故事短片", "make_story_film"),
    ("这个架构是怎么设计的", "answer"),
    ("雨夜老屋门口有一只猫", "generate_video"),
])
def test_rule_planner_routing(text, tool):
    assert ac.AgentClient._rule_plan(text)["tool"] == tool


@pytest.mark.parametrize("text,tool", [
    ("let the old man say: come inside, it is cold", "generate_talk"),
    ("make a short film about a cat", "make_story_film"),
    ("how does this space work?", "answer"),
    ("a cat watching the warm light at a rainy door", "generate_video"),
])
def test_rule_planner_english_routing(text, tool):
    """无外置大脑时英文提示词也要能正确路由（演示常被用英文提示词试）。"""
    assert ac.AgentClient._rule_plan(text)["tool"] == tool


def test_rule_planner_extracts_line_without_quotes():
    """英文/无引号写法也要能取出台词（否则演示会念默认句）。"""
    plan = ac.AgentClient._rule_plan('let the old man say: come inside, it is cold outside')
    assert plan["tool"] == "generate_talk"
    assert plan["args"]["text"] == "come inside, it is cold outside"
    plan2 = ac.AgentClient._rule_plan('让老人说：天冷了，进屋坐坐。')
    assert plan2["args"]["text"] == "天冷了，进屋坐坐。"


def test_rule_planner_extracts_quoted_line():
    plan = ac.AgentClient._rule_plan('让女孩说一句“我们回家吧”')
    assert plan["tool"] == "generate_talk"
    assert plan["args"]["text"] == "我们回家吧"


def test_build_payload_protocols():
    c = ac.AgentClient()
    p = c.build_payload("generate_video", {"prompt": "a cat", "seconds": "6", "resolution": "720p"})
    assert p == {"kind": "t2v", "resolution": "720p", "seconds": 6, "prompt": "a cat"}
    p = c.build_payload("generate_video", {"prompt": "a", "image_b64": "data:image/png;base64,AAA"})
    assert p["kind"] == "i2v" and p["image_b64"].startswith("data:image/png")
    p = c.build_payload("generate_talk", {"text": "你好", "voice": "native"})
    assert p["kind"] == "talk" and p["text"] == "你好" and p["voice"] == "native"
    p = c.build_payload("make_story_film", {"script": "父子", "segments": "4"})
    assert p["kind"] == "story" and p["segments"] == 4


def test_demo_mode_previews_payload_without_network():
    c = ac.AgentClient()          # 无 ENGINE_BASE_URL -> demo
    out = c.run_tool({"tool": "generate_video", "args": {"prompt": "雨夜", "seconds": 5}})
    assert out["ok"] and out["kind"] == "demo"
    assert out["payload"]["kind"] == "t2v" and out["payload"]["prompt"] == "雨夜"
    assert out["trace"]["request"]["kind"] == "t2v"


def test_remote_async_job_with_status_polling(monkeypatch):
    c = _client(ENGINE_BASE_URL="https://engine.example/v1/jobs",
                ENGINE_API_KEY="k", ENGINE_STATUS_URL="https://engine.example/v1/jobs")
    seen = {"posts": [], "gets": []}

    def fake_post(url, payload, key="", timeout=120):
        seen["posts"].append((url, payload, key))
        return {"job_id": "job-9"}

    seq = [{"status": "running"}, {"status": "done", "video_url": "https://cdn/x.mp4"}]

    def fake_get(url, key="", timeout=60):
        seen["gets"].append(url)
        return seq.pop(0)

    monkeypatch.setattr(c, "_post_json", fake_post)
    monkeypatch.setattr(c, "_get_json", fake_get)
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)
    out = c.run_tool({"tool": "generate_talk", "args": {"text": "你好", "image_b64": "data:image/png;base64,AA"}})
    assert out["ok"] and out["kind"] == "remote"
    assert out["task"] == "job-9" and out["video"] == "https://cdn/x.mp4"
    assert seen["posts"][0][1]["kind"] == "talk" and seen["posts"][0][2] == "k"
    assert seen["gets"] == ["https://engine.example/v1/jobs/job-9"] * 2  # 轮询到 done 才停
    # base64 不进轨迹(避免日志膨胀)
    assert out["trace"]["request"]["image_b64"] == "<base64 已省略>"


def test_remote_sync_video_url():
    c = _client(ENGINE_BASE_URL="https://engine.example/v1/jobs")
    c._post_json = lambda url, payload, key="", timeout=120: {"video_url": "https://cdn/ok.mp4"}
    out = c.run_tool({"tool": "generate_video", "args": {"prompt": "x"}})
    assert out["kind"] == "remote" and out["video"] == "https://cdn/ok.mp4"


def test_engine_error_is_human_readable():
    c = _client(ENGINE_BASE_URL="https://engine.example/v1/jobs")

    def boom(*a, **k):
        raise RuntimeError("502 Bad Gateway")

    c._post_json = boom
    out = c.run_tool({"tool": "generate_video", "args": {"prompt": "x"}})
    assert out["ok"] is False and "502" in out["text"] and out["kind"] == "error"


def test_image_injection_and_poll_job():
    c = _client(ENGINE_BASE_URL="https://engine.example/v1/jobs",
                ENGINE_STATUS_URL="https://engine.example/v1/jobs")
    got = {}
    c._post_json = lambda url, payload, key="", timeout=120: got.update(payload) or {"job_id": "j1"}
    c._get_json = lambda url, key="", timeout=60: {"status": "done", "video_url": "https://cdn/j1.mp4"}
    out = c.answer("让老人说一句话", [], image_b64="data:image/png;base64,ZZZ")
    assert got["image_b64"] == "data:image/png;base64,ZZZ"
    assert out["kind"] == "remote"
    assert c.poll_job("") == {"status": "unknown", "video_url": None}
    c._get_json = lambda url, key="", timeout=60: {"status": "running"}
    assert c.poll_job("j1")["status"] == "running"


def test_status_reports_no_secrets():
    c = _client(LLM_BASE_URL="https://llm.example/v1", LLM_API_KEY="secret-key",
                LLM_MODEL="qwen2.5-7b-instruct")
    st = c.status()
    assert st["mode"] == "agent-api" and st["brain"] is True and st["model"] == "qwen2.5-7b-instruct"
    assert "secret-key" not in json.dumps(st)
    assert "generate_talk" in st["tools"]


def test_agent_step_demo_reply_contains_payload_preview():
    r = agent_step("做一段雨夜老屋门口有猫的 5 秒镜头", [])
    assert r["history"][-1]["role"] == "assistant"
    assert "ENGINE_BASE_URL" in r["history"][-1]["content"]
    assert '\"kind\": \"t2v\"' in r["history"][-1]["content"]
    assert r["job"] is None and "generate_video" in r["trace"] and "480p" in r["trace"]


def test_agent_step_records_job_and_jobs_table():
    class FakeClient:
        mode = "agent-api"

        def answer(self, text, history, image_path="", image_b64=""):
            return {"kind": "remote", "task": "job-42", "video": "https://cdn/a.mp4",
                    "say": "已提交", "mode": "agent-api",
                    "trace": {"tool": "generate_talk", "args": {"text": "你好"}}}

        def poll_job(self, jid):
            return {"status": "done", "video_url": "https://cdn/a.mp4"}

    r = agent_step("让老人说一句“你好”", [], client=FakeClient())
    assert r["job"]["id"] == "job-42" and "job-42" in r["history"][-1]["content"]
    jobs = [r["job"]]
    md = jobs_table(jobs)
    assert "job-42" in md and "generate_talk" in md
    md2 = jobs_table(jobs, client=FakeClient(), refresh=True)
    assert "done" in md2 and "https://cdn/a.mp4" in md2
    assert "还没有任务" in jobs_table([])


def test_agent_step_never_raises():
    class Boom:
        mode = "x"

        def answer(self, *a, **k):
            raise ValueError("kaboom")

    r = agent_step("hi", [], client=Boom())
    assert r["history"] == [] or r["history"][-1]["role"] == "assistant"


def test_file_to_b64(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert ac.AgentClient.file_to_b64(str(p)).startswith("data:image/png;base64,")
    assert ac.AgentClient.file_to_b64(str(tmp_path / "nope.png")) == ""

def test_download_and_failure_paths(tmp_path, monkeypatch):
    import io
    import urllib.request

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=0: Resp(b"VIDEODATA"))
    p = ac.AgentClient.download("https://cdn.example/result.mp4", dest_dir=str(tmp_path))
    assert p and Path(p).read_bytes() == b"VIDEODATA" and p.endswith(".mp4")
    # 非 http 链接直接跳过；网络异常不抛出(界面退化为"打开原链接")
    assert ac.AgentClient.download("ftp://x/y.mp4", dest_dir=str(tmp_path)) == ""

    def boom(*a, **k):
        raise OSError("no net")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert ac.AgentClient.download("https://cdn.example/z.mp4", dest_dir=str(tmp_path)) == ""


def test_prune_outputs_keeps_latest(tmp_path):
    import os
    for i in range(15):
        f = tmp_path / ("f%d.mp4" % i)
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))
    ac.AgentClient.prune_outputs(tmp_path, keep=12)
    left = sorted(p.name for p in tmp_path.glob("*"))
    assert len(left) == 12 and "f0.mp4" not in left and "f14.mp4" in left

# ---------- 大脑自创键名 / 抖动：实测问题对应的回归测试 ----------

def test_non_url_values_never_become_addresses(monkeypatch):
    """任何非 http(s) 的脏值(实测平台把中文占位编码成了 '???')都不能被当成接口地址。"""
    os.environ["ENGINE_BASE_URL"] = "???"
    os.environ["LLM_BASE_URL"] = "???"
    os.environ["LLM_API_KEY"] = "k"
    try:
        c = ac.AgentClient()
        assert c.engine_url == "" and c.llm_base == ""
        out = c.run_tool({"tool": "generate_video", "args": {"prompt": "雨夜"}})
        assert out["kind"] == "demo" and out["ok"] is True     # 不允许出现 "unknown url type"
    finally:
        for k in ("ENGINE_BASE_URL", "LLM_BASE_URL", "LLM_API_KEY"):
            os.environ.pop(k, None)


def test_placeholder_values_are_treated_as_unset(monkeypatch):
    """空间变量不能为空(平台必填校验),所以先占位;占位符绝不能被当成真实地址。"""
    os.environ["ENGINE_BASE_URL"] = "未配置"
    os.environ["ENGINE_STATUS_URL"] = "TODO"
    os.environ["ENGINE_API_KEY"] = "-"
    os.environ["LLM_BASE_URL"] = "none"
    try:
        c = ac.AgentClient()
        assert c.engine_url == "" and c.engine_status == "" and c.engine_key == ""
        assert c.llm_base == "" and c.mode == "demo-planner"
        out = c.run_tool({"tool": "generate_video", "args": {"prompt": "雨夜"}})
        assert out["kind"] == "demo" and out["payload"]["kind"] == "t2v"
    finally:
        for k in ("ENGINE_BASE_URL", "ENGINE_STATUS_URL", "ENGINE_API_KEY", "LLM_BASE_URL"):
            os.environ.pop(k, None)


def test_llm_extra_json_is_passed_through(monkeypatch):
    """外置扩展字段(如关思考)必须原样进请求体，坏 JSON 不能把 Agent 弄崩。"""
    import os as _os
    _os.environ["LLM_BASE_URL"] = "https://llm.example/v1"
    _os.environ["LLM_API_KEY"] = "k"
    _os.environ["LLM_EXTRA_JSON"] = '{"chat_template_kwargs": {"enable_thinking": false}}'
    try:
        c = ac.AgentClient()
        seen = {}

        def fake_post(url, payload, key="", timeout=90):
            seen.update(payload)
            return {"choices": [{"message": {"content": '{"tool":"answer","args":{"text":"ok"}}'}}]}

        monkeypatch.setattr(c, "_post_json", fake_post)
        assert c.plan("随便问问", [])["tool"] == "answer"
        assert seen["chat_template_kwargs"] == {"enable_thinking": False}
        _os.environ["LLM_EXTRA_JSON"] = "not-json"
        assert ac.AgentClient().llm_extra == {}
    finally:
        for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_EXTRA_JSON"):
            _os.environ.pop(k, None)


def test_normalize_args_aliases_and_drops_unknown():
    got = ac.normalize_args("generate_talk", {"dialogue": "天冷了，进屋坐坐。", "character": "老人",
                                              "style": "realistic", "voice": "native"})
    assert got == {"text": "天冷了，进屋坐坐。", "voice": "native"}   # character/style 被丢弃
    got2 = ac.normalize_args("generate_video", {"description": "雨夜老屋", "duration": 6, "size": "720p"})
    assert got2 == {"prompt": "雨夜老屋", "seconds": 6, "resolution": "720p"}
    assert ac.normalize_args("answer", {"text": "说明"}) == {"text": "说明"}


def test_run_tool_accepts_aliased_args():
    c = ac.AgentClient()
    out = c.run_tool({"tool": "generate_talk", "args": {"dialogue": "你好", "speaker": "native"}})
    assert out["payload"]["text"] == "你好" and out["payload"]["kind"] == "talk"


def test_answer_repairs_talk_without_text(monkeypatch):
    c = ac.AgentClient()
    monkeypatch.setattr(c, "plan", lambda u, h: {"tool": "generate_talk",
                                                 "args": {"character": "老人"}, "say": "ok"})
    out = c.answer('让老人说一句“天冷了，快进屋坐坐吧。”', [])
    assert out["payload"]["kind"] == "talk"
    assert out["payload"]["text"] == "天冷了，快进屋坐坐吧。"
    assert out["trace"]["repaired"].startswith("args:text")


def test_answer_repairs_disallowed_tool(monkeypatch):
    os.environ["TOOLSET"] = "answer"
    try:
        c = ac.AgentClient()
        monkeypatch.setattr(c, "plan", lambda u, h: {"tool": "generate_video", "args": {"prompt": "x"}})
        out = c.answer("做一段雨夜老屋门口有猫的 5 秒镜头", [])
        assert out["trace"].get("repaired") == "tool-not-allowed"
    finally:
        os.environ.pop("TOOLSET", None)


def test_plan_retries_on_empty_brain_response(monkeypatch):
    os.environ["LLM_BASE_URL"] = "https://llm.example/v1"
    os.environ["LLM_API_KEY"] = "k"
    try:
        c = ac.AgentClient()
        calls = {"n": 0}

        def fake_post(url, payload, key="", timeout=90):
            calls["n"] += 1
            if calls["n"] < 3:
                return {"choices": [{"message": {"content": ""}}]}      # 实测到的抖动形态
            return {"choices": [{"message": {"content": '{"tool":"generate_video","args":{"prompt":"雨夜"}}'}}]}

        monkeypatch.setattr(c, "_post_json", fake_post)
        monkeypatch.setattr(ac.time, "sleep", lambda s: None)
        plan = c.plan("雨夜老屋", [])
        assert calls["n"] == 3 and plan["tool"] == "generate_video"
    finally:
        os.environ.pop("LLM_BASE_URL", None)
        os.environ.pop("LLM_API_KEY", None)


def test_plan_degrades_after_repeated_failure(monkeypatch):
    os.environ["LLM_BASE_URL"] = "https://llm.example/v1"
    os.environ["LLM_API_KEY"] = "k"
    try:
        c = ac.AgentClient()
        monkeypatch.setattr(c, "_post_json", lambda *a, **k: {"choices": [{"message": {"content": ""}}]})
        monkeypatch.setattr(ac.time, "sleep", lambda s: None)
        plan = c.plan("让老人说一句台词", [])
        assert plan["tool"] == "answer" and "暂不可用" in plan["args"]["text"]
    finally:
        os.environ.pop("LLM_BASE_URL", None)
        os.environ.pop("LLM_API_KEY", None)

