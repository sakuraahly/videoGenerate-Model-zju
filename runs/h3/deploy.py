#!/usr/bin/env python3
"""
h3.deploy — 运行形态（部署模式）读取与切换。

site:
  win-remote  项目在 Windows 本机，经 ssh 隧道访问 spark 的 ComfyUI/模型（默认现状）
  spark-local 项目整体部署在 spark（交付形态）：ComfyUI 与本地模型同机直连，无需隧道

用法：
  python runs/h3/deploy.py --show                 # 显示当前形态与参数
  python runs/h3/deploy.py --set spark-local      # 切换形态（并同步 llm.json base_url）
  python runs/h3/deploy.py --set win-remote
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_FILENAME = "deploy.json"
_LLM_FILE = "llm.json"
VALID_SITES = ("win-remote", "spark-local")


def deploy_path(project_dir: Path) -> Path:
    return Path(project_dir) / "config" / _FILENAME


def load_deploy(project_dir: Path) -> dict:
    p = deploy_path(project_dir)
    if not p.exists():
        # 缺省默认 win-remote，避免旧目录无配置时崩溃
        return {"site": "win-remote", "sites": {}}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def current_site(project_dir: Path) -> str:
    d = load_deploy(project_dir)
    return str(d.get("site") or "win-remote")


def site_props(deploy: dict, site: str) -> dict:
    return (deploy.get("sites") or {}).get(site) or {}


def llm_config_path(project_dir: Path) -> Path:
    return Path(project_dir) / "config" / _LLM_FILE


def sync_llm_base_url(project_dir: Path, base_url: str) -> Optional[str]:
    """把 llm.json 的 base_url 切到当前形态（先备份 .bak），返回旧值或 None。"""
    p = llm_config_path(project_dir)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    old = str(data.get("base_url") or "")
    if old == base_url:
        return old
    p.with_suffix(".json.bak").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    data["base_url"] = base_url
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return old


def set_site(project_dir: Path, site: str) -> tuple:
    """切换形态；返回 (site, props, 旧 llm base_url)。site 非法抛 ValueError。"""
    if site not in VALID_SITES:
        raise ValueError(f"未知形态: {site}（可选 {', '.join(VALID_SITES)}）")
    p = deploy_path(project_dir)
    if not p.exists():
        raise FileNotFoundError(f"缺少 {p}")
    deploy = json.loads(p.read_text(encoding="utf-8-sig"))
    deploy["site"] = site
    p.write_text(json.dumps(deploy, ensure_ascii=False, indent=2), encoding="utf-8")
    props = site_props(deploy, site)
    llm_url = str(props.get("llm_base_url") or "")
    old_llm = sync_llm_base_url(project_dir, llm_url) if llm_url else None
    return site, props, old_llm


def main(argv: Optional[list] = None) -> int:
    project_dir = Path(__file__).resolve().parent.parent.parent
    import argparse
    ap = argparse.ArgumentParser(description="运行形态切换工具")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--set", type=str, default="", metavar="site",
                    help="win-remote | spark-local")
    args = ap.parse_args(argv)
    if args.set:
        try:
            site, props, old_llm = set_site(project_dir, args.set)
        except (ValueError, FileNotFoundError) as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 3
        print(f"[deploy] 形态已切换: {site}（{props.get('label', '')}）")
        print(f"  tunnel={props.get('tunnel')} fetch={props.get('fetch')} "
              f"llm_base_url={props.get('llm_base_url')}")
        if old_llm:
            print(f"  llm.json base_url: {old_llm} -> {props.get('llm_base_url')}（旧值备份于 llm.json.bak）")
        print(f"  {props.get('notes', '')}")
        return 0
    d = load_deploy(project_dir)
    site = str(d.get("site") or "win-remote")
    props = site_props(d, site)
    print(f"当前形态: {site}（{props.get('label', '')}）")
    print(f"  tunnel={props.get('tunnel')}  comfy_probe={props.get('comfy_probe')}  "
          f"fetch={props.get('fetch')}")
    print(f"  llm_base_url={props.get('llm_base_url')}（config/llm.json 当前 base_url 以文件为准）")
    print(f"  {props.get('notes', '')}")
    print("切换：python runs\\h3\\deploy.py --set <win-remote|spark-local>，或 bats\\config\\mode.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
