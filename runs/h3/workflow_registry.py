#!/usr/bin/env python3
"""workflow_registry — 工作流注册表适配器（book-12 步骤1）。

单一来源：config/capabilities.json 的 workflows 条目（含 stage/template/slots/
prompt_inject/params/features/enabled）。本模块提供 load/resolve/template_health/
validate_all，供 tools.py / refimage / prompts / h3_submit / consistency_check
按表驱动（去硬编码），新增/禁用/更换工作流 = 改注册表 + validate。

约定：
- resolve(stage_or_id)：stage 键（t2v/i2v/r2v/flf2v）或注册表 id（video_t2v/...）均可。
- 已禁用（enabled=false）→ resolve 返回 None 并给出 reason（调用方提示禁用原因）。
- template_health：模板存在、JSON 可解析、prompt 注入节点存在、图片槽位数满足
  规格；失败给出可读原因，绝不静默错注入。
- validate_all：逐条 template_health + 注册表 schema 完整性。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

from h3 import capabilities as capmod


def load_registry(project_dir: Path) -> dict:
    """加载能力注册表（capabilities.json）。"""
    return capmod.load_capabilities(project_dir)


def local_entries(cap: dict) -> list:
    """engine=local 的全部工作流条目（含禁用，供管理面使用）。"""
    return [w for w in (cap.get("workflows") or []) if w.get("engine") == "local"]


def _match(entry: dict, key: str) -> bool:
    return entry.get("stage") == key or entry.get("id") == key or entry.get("slot") == key


def resolve(cap: dict, key: str) -> Tuple[Optional[dict], str]:
    """按 stage/id/slot 解析工作流；返回 (条目|None, 说明)。

    - 未注册 → (None, "未知工作流: <key>（可用: <enabled ids>）")
    - 已禁用   → (None, "工作流 <id> 已禁用（enabled=false）")
    """
    entries = local_entries(cap)
    hit = next((w for w in entries if _match(w, key)), None)
    if hit is None:
        avail = ", ".join(e.get("id") for e in entries if e.get("enabled", True))
        return None, f"未知工作流: {key}（已注册可用: {avail}）"
    if not hit.get("enabled", True):
        return None, f"工作流 {hit.get('id')} 已禁用（enabled=false）"
    return hit, ""


def enabled_stages(cap: dict) -> list:
    """可用 stage 键列表（按注册表）。"""
    return [e["stage"] for e in local_entries(cap) if e.get("enabled", True)]


def template_path(project_dir: Path, entry: dict) -> Path:
    return project_dir / str(entry.get("template", ""))


def params_for(entry: dict) -> dict:
    """参数上限/默认（注册表 params 节；缺失给保守默认）。"""
    return entry.get("params") or {}


def slot_spec(entry: dict) -> dict:
    """槽位规格（images/videos/audios 的角色与数量）。"""
    s = entry.get("slots") or {}
    return {"images": s.get("images") or [], "videos": s.get("videos") or [],
            "audios": s.get("audios") or []}


def image_slot_count(spec: dict) -> int:
    return sum(int(x.get("count", 0)) for x in spec.get("images", []))


def _load_json(tpl: Path) -> Optional[dict]:
    try:
        return json.loads(tpl.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def template_health(project_dir: Path, entry: dict) -> Tuple[bool, list]:
    """模板健康检查：返回 (ok, 说明列表)。"""
    issues: list = []
    tpl = template_path(project_dir, entry)
    if not tpl.exists():
        return False, [f"模板缺失: {entry.get('template')}"]
    d = _load_json(tpl)
    if d is None:
        return False, [f"模板 JSON 无法解析: {tpl.name}"]
    nodes = d.get("nodes") if isinstance(d, dict) else None
    if nodes is None:
        # API 格式模板：检查注入 api_key 是否存在
        inj = entry.get("prompt_inject") or {}
        api_key = inj.get("api_key")
        if api_key:
            found = any(isinstance(n, dict) and api_key in (n.get("inputs") or {})
                        for n in d.values() if isinstance(n, dict))
            if not found:
                issues.append(f"注入点 api_key 未找到: {api_key}")
        return (len(issues) == 0), issues
    # UI 格式探针
    inj = entry.get("prompt_inject") or {}
    ntype = inj.get("node_type")
    widx = int(inj.get("widget_index", 0))
    if ntype:
        hit = [n for n in nodes if n.get("type") == ntype]
        if not hit:
            issues.append(f"prompt 注入节点类型未找到: {ntype}")
        else:
            wv = hit[0].get("widgets_values") or []
            if len(wv) <= widx or not str(wv[widx]).strip():
                issues.append(f"注入 widget 为空: {ntype}[{widx}]")
    # 图片槽位数
    need = image_slot_count(slot_spec(entry))
    got = sum(1 for n in nodes if n.get("type") == "LoadImage")
    if need and got < need:
        issues.append(f"LoadImage 槽位不足: 期望 {need} 实际 {got}")
    return (len(issues) == 0), issues


def validate_all(project_dir: Path) -> list:
    """全部本地工作流：schema 完整性 + template_health。返回 [(id, ok, issues)]。"""
    cap = load_registry(project_dir)
    out = []
    for e in local_entries(cap):
        issues = []
        for must in ("stage", "template", "enabled", "slots", "prompt_inject",
                     "params", "features"):
            if must not in e:
                issues.append(f"缺字段: {must}")
        ok, tl = template_health(project_dir, e)
        if not ok:
            issues.extend(tl)
        out.append((e.get("id"), not issues, issues))
    return out


def digest_entries(cap: dict) -> str:
    """把「当前可用工作流+参数范围+特性」压缩成一段文本（给 agent 动态认知）。"""
    lines = []
    for e in local_entries(cap):
        if not e.get("enabled", True):
            continue
        p = e.get("params") or {}
        res = ",".join(p.get("resolutions") or [])
        sec = p.get("seconds") or {}
        feat = [k for k, v in (e.get("features") or {}).items() if v]
        slots = slot_spec(e)
        img = ", ".join(f"{s['role']}x{s['count']}" for s in slots["images"]) or "none"
        lines.append(
            f"- {e.get('id')} (stage={e.get('stage')}): images={img} "
            f"resolutions=[{res}] seconds={sec.get('min')}..{sec.get('max')} "
            f"features={','.join(feat) or 'none'}")
    return "\n".join(lines)
