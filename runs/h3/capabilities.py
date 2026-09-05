#!/usr/bin/env python3
"""
h3.capabilities — 项目生成能力的结构化注册表（config/capabilities.json）访问层。

作用（方案一：System Prompt + 结构化工具/能力定义的基础）：
  1) 单一来源：能力/工作流/参数只在 capabilities.json 维护，避免散落文档漂移；
  2) 生成人类可读说明：`python runs/h3/capabilities.py --doc` 产出 docs/capabilities-ai.md；
  3) 生成“喂给本地 LLM”的精简摘要：digest（默认不注入每次填词请求，避免挤占指令；
     供未来“创意→选工作流/出计划”的 plan 模式使用，或人工审查模型能看到什么）。
  4) 校验：运行方可用 load_workflow() 判断某槽位/引擎存在性。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_RUNS_DIR = str(Path(__file__).resolve().parent.parent)
if _RUNS_DIR not in sys.path:  # book-12：直接运行时自举 runs/ 到 path
    sys.path.insert(0, _RUNS_DIR)

_FILENAME = "capabilities.json"


def capabilities_path(project_dir: Path) -> Path:
    return Path(project_dir) / "config" / _FILENAME


def load_capabilities(project_dir: Path) -> dict:
    p = capabilities_path(project_dir)
    if not p.exists():
        raise FileNotFoundError(f"缺少能力注册表: {p}")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def workflow_by_id(cap: dict, wid: str) -> Optional[dict]:
    return next((w for w in (cap.get("workflows") or []) if w.get("id") == wid), None)


def llm_digest(cap: dict) -> str:
    """压缩版能力摘要（给本地 LLM 的 system 上下文；一行式、小模型友好）。

    只列本地工作流组（engine=local）；云端 api_* 不在使用范围，不向模型提及。
    """
    wf = [f"{w['id']}({w.get('needs_images', 'none')})"
          for w in (cap.get("workflows") or []) if w.get("engine") == "local"]
    lines = [
        f"Local workflow group (the ONLY workflows in use): {', '.join(wf)}.",
        "Run a workflow: python runs/h3_submit.py --stage <workflow_id> "
        "[--resolution 360p|480p|540p|720p|768p] [--seconds 5..15] [--seed N] [--dry-run to preview].",
        "Make a reference image: python runs/h3_text2img_flux.py --text '<English description>' "
        "--name <id> [--width 1344 --height 768].",
        "Prompt text you produce must follow config/prompt_blueprints.json "
        "(English positive/negative JSON, include an audio line, end with negative constraints).",
    ]
    return "\n".join(lines)


def markdown_doc(cap: dict) -> str:
    local_wf = [x for x in (cap.get("workflows") or []) if x.get("engine") == "local"]
    has_cloud = any(x.get("engine") != "local" for x in (cap.get("workflows") or []))
    w = "\n".join(
        f"| `{x['id']}` | {x.get('purpose', '')} | `{x.get('engine')}` | "
        f"{x.get('needs_images', 'none')} | `{x.get('slot')}` |"
        for x in local_wf)
    cloud_note = ("\n\n> 注：云端 api_*（Comfy 登录）不在使用范围，已从能力面剔除；"
                  "本地同语义由 video_* 四类覆盖。") if has_cloud else ""
    tools = []
    for t in cap.get("tools") or []:
        p = "\n".join(f"  - `{k}` ({v.get('type')}): {v.get('description', '')}"
                      + (f"，默认 {v.get('default')}" if v.get("default") is not None else "")
                      for k, v in (t.get("params") or {}).items())
        tools.append(f"### {t['name']}\n{t.get('description', '')}\n\n用法：\n```\n"
                     f"{t.get('usage', '')}\n```\n\n参数：\n{p}")
    return f"""# 项目生成能力（自动生成：由 config/capabilities.json 生成，勿手改本文件）

引擎：`{cap['engine'].get('name')}` @ {cap['engine'].get('host')}
模型：视频 {cap['engine']['models'].get('video')}；文生图 {cap['engine']['models'].get('image')}；LLM {cap['engine']['models'].get('llm')}

## 视频工作流（本地组，唯一实际使用）

| id | 用途 | 引擎 | 图需求 | 提示词槽位 |
|---|---|---|---|---|
{w}
{cloud_note}

- 槽位文件：`{cap['prompt_slots']['file_pattern']}`；空/缺失回退 default（`prompts/positive_prompts.txt`）；编辑入口 `{cap['prompt_slots']['editor']}`。

## 工具（tools）

{chr(10).join(tools)}

## 给 LLM 的提示
{cap.get('note_for_llm', '')}

## LLM 职责边界（强约束，勿绕过）
{cap.get('llm_role_guard', '')}

## 产物拉取策略
{cap.get('download_policy', '')}
"""


_WF_BLOCK_MARKERS = ("═══ 工作流（只用本地，不提 api_*） ═══",
                    "═══ 工作流（只用本地，不提 api_*）═══")
_WF_DYN_MARKER = "═══ 工作流（注册表动态声明，book-12）═══"


def agent_digest(project_dir: Path) -> str:
    """book-12 A4：注册表当前可用能力摘要（enabled 工作流+参数范围+特性）。失败返回空串。"""
    try:
        from h3 import workflow_registry
        cap = workflow_registry.load_registry(project_dir)
        return workflow_registry.digest_entries(cap)
    except Exception:  # noqa: BLE001
        return ""


def compose_system_message(sys_msg: str, digest: str) -> str:
    """把 SYSTEM_MESSAGE 中硬编码工作流清单段替换为注册表 digest 段（A4 动态认知）。
    digest 为空则原样返回。
    """
    if not digest:
        return sys_msg
    idx = -1
    for _mk in _WF_BLOCK_MARKERS:
        idx = sys_msg.find(_mk)
        if idx >= 0:
            break
    if idx < 0:
        return sys_msg + "\n\n" + _WF_DYN_MARKER + "\n" + digest
    nxt = sys_msg.find("\n\n", idx + 1)
    if nxt < 0:
        # 块后无空行：取该行行尾，保守保留后续
        nxt = sys_msg.find("\n", idx + 1)
        nxt = sys_msg.find("\n", nxt + 1) if nxt > 0 else len(sys_msg)
        if nxt < 0:
            nxt = len(sys_msg)
    return sys_msg[:idx] + _WF_DYN_MARKER + "\n" + digest + sys_msg[nxt:]


def write_registry_doc(project_dir: Path) -> Path:
    """生成 docs/agent-reading/05-workflows-registry.md（agent 可读；自动生成，勿手改）。"""
    from h3 import workflow_registry
    cap = workflow_registry.load_registry(project_dir)
    lines = ["# 工作流注册表（自动生成，勿手改）", "",
             "> 来源: config/capabilities.json；重新生成: python runs/h3/capabilities.py --registry-doc", ""]
    entries = [e for e in workflow_registry.local_entries(cap) if e.get("enabled", True)]
    for e in entries:
        lines.append(f"## {e.get('id')} (stage={e.get('stage')})")
        lines.append("")
        lines.append(f"- 用途: {e.get('purpose', '')}")
        lines.append(f"- 模板: `{e.get('template')}`（format={e.get('format')}）")
        slots = workflow_registry.slot_spec(e)
        img = ", ".join(f"{s.get('role')}x{s.get('count')}" for s in slots["images"]) or "none"
        lines.append(f"- 槽位: images={img}; videos={len(slots['videos'])}; audios={len(slots['audios'])}")
        p = e.get("params") or {}
        sec = p.get("seconds") or {}
        lines.append(f"- 参数: resolutions={','.join(p.get('resolutions') or [])}; "
                     f"seconds={sec.get('min')}..{sec.get('max')}; fps={p.get('fps')}; steps={p.get('steps')}")
        lines.append(f"- 特性: {', '.join(k for k, v in (e.get('features') or {}).items() if v) or 'none'}")
        lines.append("")
    lines.append("## 当前全部可用（digest）")
    lines.append("")
    lines.append(workflow_registry.digest_entries(cap))
    lines.append("")
    dst = project_dir / "docs" / "agent-reading" / "05-workflows-registry.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines), encoding="utf-8")
    return dst


def main(argv: Optional[List[str]] = None) -> int:
    project_dir = Path(__file__).resolve().parent.parent.parent  # 项目根（runs/h3 → 根）
    cap = load_capabilities(project_dir)
    import argparse
    ap = argparse.ArgumentParser(description="capabilities 注册表工具")
    ap.add_argument("--doc", action="store_true", help="打印并写回 docs/capabilities-ai.md")
    ap.add_argument("--digest", action="store_true", help="打印喂给 LLM 的精简摘要")
    ap.add_argument("--workflow", type=str, default="", help="查询某个 workflow id")
    ap.add_argument("--registry-doc", action="store_true",
                    help="生成 docs/agent-reading/05-workflows-registry.md（agent 动态认知文档）")
    ap.add_argument("--digest2", action="store_true", help="打印注册表动态摘要（A4 用）")
    args = ap.parse_args(argv)
    if args.doc:
        md = markdown_doc(cap)
        dst = project_dir / "docs" / "capabilities-ai.md"
        dst.write_text(md, encoding="utf-8")
        print(md[:400])
        print(f"\n[written] {dst}")
    elif args.digest:
        print(llm_digest(cap))
    elif args.digest2:
        print(agent_digest(project_dir))
    elif args.registry_doc:
        dst = write_registry_doc(project_dir)
        print(f"[written] {dst}")
    elif args.workflow:
        w = workflow_by_id(cap, args.workflow)
        if w:
            print(json.dumps(w, ensure_ascii=False, indent=2))
        else:
            print(f"未知 workflow: {args.workflow}", file=sys.stderr)
            return 3
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
