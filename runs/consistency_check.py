#!/usr/bin/env python3
"""
consistency_check — 本地项目静态一致性 / 潜在冲突审计（只读，不调用 ComfyUI/Qwen）。

检查项：
 1) prompts/manifest.json：槽位文件存在性、workflow_files 模板文件存在性
 2) config/pipeline.json：stages 模板文件存在、default_stage 合法、builtin 值合法
 3) config/capabilities.json：workflows 与 manifest workflow_files 名称集合一致
 4) 模板(remote_workflows/*.json) LoadImage 引用图 与 spark ~/ai/ComfyUI/input 比对
 5) 提示词文件多段拼接残留（含 "--- 注入" 分隔的多版本提示词 = 潜在内容冲突提示）
 6) 本地根残留/临时文件（*.tar / .sync* 等）与 git 未跟踪清单
用法：python runs/consistency_check.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIRROR = ROOT / "workflows" / "remote_workflows"
ISSUES = []
NOTES = []


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def check_manifest():
    p = ROOT / "prompts" / "manifest.json"
    if not p.exists():
        ISSUES.append("manifest.json 缺失")
        return
    m = jload(p)
    slots = m.get("slots") or {}
    # 槽位文件缺失/为空 = 回退 default（设计特性），仅记录；default 两文件必须存在
    d = m.get("default") or {}
    for key in ("positive", "negative"):
        rel = d.get(key)
        if rel and not (ROOT / rel).exists():
            ISSUES.append(f"manifest default.{key} 文件缺失: {rel}")
    missing_slots = []
    for name, s in slots.items():
        for key in ("positive", "negative"):
            rel = s.get(key)
            if rel and not (ROOT / rel).exists():
                missing_slots.append(f"{name}.{key}")
    if missing_slots:
        NOTES.append(f"槽位文件缺失（将回退 default，符合设计）: {', '.join(missing_slots)}")
    for wf, slot in (m.get("workflow_files") or {}).items():
        if not (MIRROR / wf).exists():
            ISSUES.append(f"manifest workflow_files 模板缺失: {wf}")
        if wf.endswith(".json") and wf not in [x.name for x in MIRROR.glob("*.json")]:
            NOTES.append(f"workflow_files {wf} 不在镜像目录（可能本地扩展）")
    NOTES.append(f"manifest 槽位数: {len(slots) + 1}（default+{len(slots)}）")


def check_pipeline():
    p = ROOT / "config" / "pipeline.json"
    if not p.exists():
        ISSUES.append("pipeline.json 缺失")
        return
    cfg = jload(p)
    default = cfg.get("default_stage")
    stages = cfg.get("stages") or {}
    if default not in stages:
        ISSUES.append(f"default_stage={default} 不在 stages 中: {sorted(stages)}")
    for sid, st in stages.items():
        tpl = st.get("template")
        if tpl:
            tp = ROOT / cfg.get("templates_dir", "workflows/remote_workflows") / tpl
            if not tp.exists():
                if "待" in str(st.get("description") or "") or sid in ("character", "keyframes"):
                    NOTES.append(f"stage {sid} 模板为占位（待启用）: {tpl}")
                else:
                    ISSUES.append(f"stage {sid} 模板缺失: {tpl}")
        b = st.get("builtin")
        if b and b != "h3_t2v":
            ISSUES.append(f"stage {sid} builtin 未知: {b}")


def check_capabilities_vs_manifest():
    cap = jload(ROOT / "config" / "capabilities.json")
    man = jload(ROOT / "prompts" / "manifest.json")
    cap_ids = {w["id"] for w in cap.get("workflows", [])}
    man_wf = {Path(x).stem.replace("minimax_h3_", "minimax_h3_") for x in man.get("workflow_files", {})}
    man_slots = set(man.get("slots", {}))
    # capabilities id (video_t2v…) 应对应 manifest slot（video_t2v 等）
    for cid in cap_ids:
        if cid not in man_slots:
            ISSUES.append(f"capabilities workflow {cid} 缺 manifest 槽位")
    # manifest workflow_files 数量 与 capabilities workflows 应一致（7）
    if len(man.get("workflow_files", {})) != len(cap_ids):
        NOTES.append(f"workflow_files({len(man.get('workflow_files', {}))}) 与 "
                     f"capabilities workflows({len(cap_ids)}) 数量不同")


def check_templates_images():
    """模板 LoadImage 引用图 与 spark input 比对（仅 ls，不启服务）。"""
    refs = set()
    for jf in sorted(MIRROR.glob("*.json")):
        ui = jload(jf)
        for n in ui.get("nodes", []):
            if n.get("type") == "LoadImage":
                v = (n.get("widgets_values") or [""])[0]
                if v:
                    refs.add((jf.name, str(v)))
    if not refs:
        return
    # spark-local：input 在本机，直接 ls；win-remote：经 ssh ls spark
    site = "win-remote"
    try:
        dep = jload(ROOT / "config" / "deploy.json")
        site = dep.get("site") or site
    except Exception:
        pass
    have = set()
    if site == "spark-local":
        indir = (Path.home() / "ai" / "ComfyUI" / "input")
        have = {p.name for p in indir.glob("*")} if indir.is_dir() else set()
    else:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "spark",
                            "ls -1 ~/ai/ComfyUI/input/ 2>/dev/null"],
                           capture_output=True, text=True, timeout=60)
        have = set(r.stdout.splitlines()) if r.returncode == 0 else set()
    for fname, img in sorted(refs):
        if img not in have:
            ISSUES.append(f"模板 {fname} 引用图不在 spark input: {img}")


def check_prompt_multi_injection():
    for f in sorted((ROOT / "prompts" / "workflows").glob("*.txt")):
        t = f.read_text(encoding="utf-8-sig")
        if "--- 注入" in t:
            seg = t.count("--- 注入")
            NOTES.append(f"提示词 {f.name} 含 {seg} 段注入标记（多版本拼接，请人工整理）")


def check_leftovers_and_git():
    for pat in ("*.tar", ".sync*", "proj_merge.tar"):
        for f in ROOT.glob(pat):
            if f.name not in (".sync-state.json",):
                NOTES.append(f"本地根残留文件: {f.name}")
    g = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                       capture_output=True, text=True)
    unt = [ln for ln in g.stdout.splitlines() if ln.startswith("??")]
    mod = [ln for ln in g.stdout.splitlines() if ln.startswith(" M") or ln.startswith("M")]
    if unt:
        NOTES.append(f"git 未跟踪 {len(unt)} 项（并行写入？）: {[u[3:] for u in unt[:6]]}")
    if mod:
        NOTES.append(f"git 已修改未提交 {len(mod)} 项")


def main() -> int:
    for fn in (check_manifest, check_pipeline, check_capabilities_vs_manifest,
               check_templates_images, check_prompt_multi_injection,
               check_leftovers_and_git):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            ISSUES.append(f"[{fn.__name__}] 检查异常: {e}")
    print(f"== 一致性审计：问题 {len(ISSUES)} / 提示 {len(NOTES)} ==")
    for i in ISSUES:
        print("  [问题]", i)
    for n in NOTES:
        print("  [提示]", n)
    return 1 if ISSUES else 0


if __name__ == "__main__":
    sys.exit(main())
