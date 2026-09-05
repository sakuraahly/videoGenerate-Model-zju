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


def inject_spec(entry: dict) -> dict:
    """提示词注入点（book-12：由注册表声明，替代 basename 启发式）。
    形如 {"class_prefix": "MiniMaxH3", "positive_key": "prompt", "negative_key": "negative_prompt"}。
    """
    return entry.get("inject_spec") or {}


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


def _load_capfile(cap_path: Path) -> dict:
    if not cap_path.exists():
        raise FileNotFoundError(f"缺少能力注册表: {cap_path}")
    import json as _json
    return _json.loads(cap_path.read_text(encoding="utf-8-sig"))


def _save(cap_path: Path, cap: dict) -> None:
    import json as _json
    if not cap_path.parent.exists():
        cap_path.parent.mkdir(parents=True, exist_ok=True)
    cap_path.write_text(_json.dumps(cap, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def set_enabled(cap_path: Path, key: str, enabled: bool) -> tuple:
    """启用/禁用某个 local 工作流（按 stage/id/slot 识别）。返回 (ok, 说明)。"""
    cap = _load_capfile(cap_path)
    hit = next((w for w in local_entries(cap) if _match(w, key)), None)
    if hit is None:
        return False, f"未找到工作流: {key}"
    hit["enabled"] = bool(enabled)
    _save(cap_path, cap)
    return True, f"{hit['id']} 已{'启用' if enabled else '禁用'}"


def add_local(cap_path: Path, wid: str, template: str, **kw) -> tuple:
    """新增一个 local 工作流条目（最小声明；随后用 validate 补齐字段）。
    返回 (ok, 说明)。
    """
    cap = _load_capfile(cap_path)
    if any(w.get("id") == wid for w in cap.get("workflows") or []):
        return False, f"id 已存在: {wid}"
    entry = {
        "id": wid, "engine": "local", "stage": str(kw.get("stage") or wid),
        "purpose": str(kw.get("purpose") or "待填: 用途说明"),
        "needs_images": str(kw.get("needs_images") or "unknown"),
        "slot": wid, "enabled": True,
        "template": template, "format": kw.get("format") or "ui",
        "slots": {"images": [], "videos": [], "audios": []},
        "prompt_inject": {},
        "inject_spec": {},
        "params": {"resolutions": kw.get("resolutions") or ["360p", "480p", "540p", "720p", "768p"],
                    "seconds": {"min": 5, "max": 15}, "fps": 24, "steps": 20, "seed": "12345"},
        "features": {"reference_videos": False, "per_segment": False, "audio": False,
                     "negative_support": True},
    }
    cap.setdefault("workflows", []).append(entry)
    _save(cap_path, cap)
    return True, f"已登记 {wid} (stage={entry['stage']})；请补全 slots/inject_spec 并 validate"


def swap_template(cap_path: Path, key: str, new_template: str, record_sha: bool = True) -> tuple:
    """更换模板路径（sha 留痕可回滚）。返回 (ok, 说明)。"""
    import hashlib as _hl
    import datetime as _dt
    cap = _load_capfile(cap_path)
    hit = next((w for w in local_entries(cap) if _match(w, key)), None)
    if hit is None:
        return False, f"未找到工作流: {key}"
    old = str(hit.get("template") or "")
    old_path = cap_path.parent / old
    hit["template"] = new_template
    if record_sha:
        hist = list(hit.get("template_sha_history") or [])
        sha = ""
        try:
            sha = _hl.sha256((cap_path.parent / new_template).read_bytes()).hexdigest()[:16]
        except OSError:
            pass
        hist.append({"ts": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "from": old, "to": new_template, "sha": sha})
        hit["template_sha_history"] = hist
    _save(cap_path, cap)
    return True, f"{hit['id']}: {old} -> {new_template}（sha 留痕）"


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
