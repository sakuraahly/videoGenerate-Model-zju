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
    """压缩版能力摘要（给本地 LLM 的 system 上下文；一行式、小模型友好）。"""
    wf = []
    for w in cap.get("workflows") or []:
        eng = "L" if w.get("engine") == "local" else "C"
        wf.append(f"{w['id']}({eng},{w.get('needs_images', 'none')})")
    lines = [
        f"Available video workflows: {', '.join(wf)} "
        "(L=local inference on spark, C=Comfy-cloud login required).",
        "Run a workflow: python runs/h3_submit.py --stage <workflow_id> "
        "[--resolution 360p|480p|540p|720p|768p] [--seconds 5..15] [--seed N] [--dry-run to preview].",
        "Make a reference image: python runs/h3_text2img_flux.py --text '<English description>' "
        "--name <id> [--width 1344 --height 768].",
        "Prompt text you produce must follow config/prompt_blueprints.json "
        "(English positive/negative JSON, include an audio line, end with negative constraints).",
    ]
    return "\n".join(lines)


def markdown_doc(cap: dict) -> str:
    w = "\n".join(
        f"| `{x['id']}` | {x.get('purpose', '')} | `{x.get('engine')}` | "
        f"{x.get('needs_images', 'none')} | `{x.get('slot')}` |"
        for x in cap.get("workflows") or [])
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

## 视频工作流（workflows）

| id | 用途 | 引擎 | 图需求 | 提示词槽位 |
|---|---|---|---|---|
{w}

- 槽位文件：`{cap['prompt_slots']['file_pattern']}`；空/缺失回退 default（`prompts/positive_prompts.txt`）；编辑入口 `{cap['prompt_slots']['editor']}`。

## 工具（tools）

{chr(10).join(tools)}

## 给 LLM 的提示
{cap.get('note_for_llm', '')}
"""


def main(argv: Optional[List[str]] = None) -> int:
    project_dir = Path(__file__).resolve().parent.parent.parent  # 项目根（runs/h3 → 根）
    cap = load_capabilities(project_dir)
    import argparse
    ap = argparse.ArgumentParser(description="capabilities 注册表工具")
    ap.add_argument("--doc", action="store_true", help="打印并写回 docs/capabilities-ai.md")
    ap.add_argument("--digest", action="store_true", help="打印喂给 LLM 的精简摘要")
    ap.add_argument("--workflow", type=str, default="", help="查询某个 workflow id")
    args = ap.parse_args(argv)
    if args.doc:
        md = markdown_doc(cap)
        dst = project_dir / "docs" / "capabilities-ai.md"
        dst.write_text(md, encoding="utf-8")
        print(md[:400])
        print(f"\n[written] {dst}")
    elif args.digest:
        print(llm_digest(cap))
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
