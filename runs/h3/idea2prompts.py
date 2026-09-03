#!/usr/bin/env python3
"""
idea2prompts — 单一创意 → 全部工作流提示词（中间通用模型桥）

人的入口只有一句创意（--idea 或 --idea-file）；本脚本调用 config/llm.json 里
配置的通用模型（OpenAI 兼容 /chat/completions），按 config/prompt_blueprints.json
给每个提示词槽生成 {positive, negative}，写入 prompts/workflows/<slot>.*.txt
（default 槽写 prompts/positive_prompts.txt 等）。

用法：
  python runs/h3/idea2prompts.py --idea "一段创意" --dry-run   # 打印计划/系统消息，不发请求
  python runs/h3/idea2prompts.py --list                        # 列出槽位
  python runs/h3/idea2prompts.py --idea "..." --workflow video_r2v
  python runs/h3/idea2prompts.py --idea-file brief.txt
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 允许以脚本直接运行（python runs/h3/idea2prompts.py）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from h3 import prompts as h3prompts  # noqa: E402
from h3.params import ParamError, project_root_from_file  # noqa: E402

_LLM_FILE = "llm.json"
_BLUEPRINTS_FILE = "prompt_blueprints.json"


def load_llm_config(project_dir: Path) -> dict:
    path = Path(project_dir) / "config" / _LLM_FILE
    if not path.exists():
        raise ParamError(f"缺少 AI 配置：{path}（可复制 config/llm.example.json 修改）。")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise ParamError(f"AI 配置解析失败 {path}: {e}")
    return {
        "enabled": bool(data.get("enabled", False)),
        "kind": str(data.get("kind") or "openai_compatible"),
        "base_url": str(data.get("base_url") or "").rstrip("/"),
        "api_key": str(data.get("api_key") or ""),
        "model": str(data.get("model") or ""),
        "temperature": float(data.get("temperature", 0.7)),
        "timeout": int(data.get("timeout_seconds", 120)),
    }


def load_blueprints(project_dir: Path) -> dict:
    path = Path(project_dir) / "config" / _BLUEPRINTS_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"global_rules": "", "slots": {}}


def chat_once(cfg: dict, messages: list) -> str:
    if cfg.get("kind") != "openai_compatible":
        raise ParamError(f"暂不支持 kind={cfg.get('kind')}（当前仅 openai_compatible）。")
    url = f"{cfg['base_url']}/chat/completions"
    payload = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg["temperature"],
    }).encode("utf-8")
    # 本地自部署端点（spark vLLM/Ollama 等）通常无密钥：api_key 为空时不发
    # Authorization 头（空 Bearer 可能被部分服务以 401 拒绝）。
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise ParamError(f"AI 请求失败 HTTP {e.code}: {body[:500]}")
    except (urllib.error.URLError, OSError) as e:
        raise ParamError(f"AI 请求失败（网络/配置）：{e}")
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return content


def parse_prompt_json(text: str, slot: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t else t
    if t.startswith("```json"):
        t = t[7:]
    t = t.strip().strip("`").strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        # 允许纯文本回退：当作 positive
        return {"positive": t, "negative": ""}
    if not isinstance(obj, dict):
        raise ParamError(f"槽位 {slot} 的 AI 输出不是 JSON 对象。")
    return {
        "positive": str(obj.get("positive") or ""),
        "negative": str(obj.get("negative") or ""),
    }


def slot_list(project_dir: Path) -> list:
    m = h3prompts.load_manifest(project_dir)
    ids = ["default"] + sorted((m.get("slots") or {}).keys())
    return ids


def build_messages(idea: str, slot: str, blueprints: dict,
                   manifest: dict) -> list:
    rules = blueprints.get("global_rules") or ""
    b = ((blueprints.get("slots") or {}).get(slot) or {})
    label = str(b.get("label") or slot)
    extra = str(b.get("extra") or "")
    sys_prompt = (
        "你是影视分镜提示词撰写器。只输出可直接运行的 JSON："
        '{"positive": "...", "negative": "..."}。不要多余文字。\n规则：' + rules
    )
    user_prompt = (
        f"目标提示词槽位：{slot}（{label}）\n槽位说明：{extra}\n"
        f"人的创意：{idea}\n请为该槽位生成正向与负向提示词。"
    )
    return [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="单一创意 → 各工作流提示词")
    ap.add_argument("--idea", type=str, default=None)
    ap.add_argument("--idea-file", type=str, default=None)
    ap.add_argument("--workflow", type=str, default="", help="只生成某槽位（如 video_r2v）")
    ap.add_argument("--list", action="store_true", help="列出槽位")
    ap.add_argument("--dry-run", action="store_true", help="只打印消息/计划，不发请求不写文件")
    ap.add_argument("--force", action="store_true", help="AI 关闭时也允许纯文本占位写入（测试用）")
    args = ap.parse_args(argv)

    project_dir = project_root_from_file(Path(__file__))
    if args.list:
        for s in slot_list(project_dir):
            print(s)
        return 0

    idea = args.idea
    if args.idea_file:
        idea = Path(args.idea_file).read_text(encoding="utf-8-sig").strip()
    if not idea:
        raise ParamError("请用 --idea 或 --idea-file 给一段创意。")

    cfg = load_llm_config(project_dir)
    blueprints = load_blueprints(project_dir)
    m = h3prompts.load_manifest(project_dir)
    slots = [args.workflow] if args.workflow else slot_list(project_dir)

    print(f"[idea2prompts] 创意: {idea[:120]}{'...' if len(idea) > 120 else ''}")
    for slot in slots:
        msgs = build_messages(idea, slot, blueprints, m)
        print(f"  - {slot}")
        if args.dry_run:
            print(f"      system: {msgs[0]['content'][:120]}...")
            print(f"      user  : {msgs[1]['content'][:160]}...")
            continue
        if not cfg.get("enabled"):
            if args.force:
                out = json.dumps({"positive": idea, "negative": ""})
            else:
                raise ParamError(
                    "AI(enabled=false)：请在 config/llm.json 填 base_url/model 并把 enabled "
                    "设为 true（本地 spark vLLM/Qwen3 参考 config/llm.spark-qwen3.example.json，"
                    "api_key 可留空；公网服务需 api_key）；或先 --dry-run 预览。")
        else:
            raw = chat_once(cfg, msgs)
            out = parse_prompt_json(raw, slot)
        if slot == "default":
            h3prompts.write_slot_texts(project_dir, None, out["positive"], out["negative"],
                                       defaults=True)
        else:
            h3prompts.write_slot_texts(project_dir, slot, out["positive"], out["negative"])
        print(f"      ok positive={len(out['positive'])}ch negative={len(out['negative'])}ch")
    print("完成。" if not args.dry_run else "(dry-run 预览，未请求/写入)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ParamError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(90)
