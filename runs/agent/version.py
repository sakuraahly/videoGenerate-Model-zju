#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runs/agent/version.py — 版本指纹（唯一来源，book-01 步骤 3）。

用途：让「当前运行实例是哪个代码」一眼可查、可核对（防「跑的是旧代码/旧进程」类假绿）。
策略：
  1. 优先 git rev-parse --short HEAD（运行仓库）；空/失败 → 2；
  2. 兜底：关键文件（scheduler/ui_app/tools）内容指纹 sha1[:10]，前缀 file:。

用法：
    from runs.agent import version
    print(version.AGENT_VERSION)      # 如 5b97538 或 file:abc123def4
    print(version.describe())         # 多行：版本 + root + 形态
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

_CACHE: dict = {}


def project_root() -> Path:
    """项目根：以本文件位置为准（最可靠）；env 仅在指向真实仓库时作覆盖。

    注意：scheduler.py 会把 VIDEOGEN_PROJECT_ROOT 设为 expanduser('~/...')，
    该值在 Windows 上会落到 C:/Users/<user> 的残留副本——切勿直接信任 env。
    """
    via_file = Path(__file__).resolve().parent.parent.parent
    if (via_file / "runs").is_dir():
        return via_file
    env = os.environ.get("VIDEOGEN_PROJECT_ROOT", "").strip()
    if env and (Path(env) / "runs").is_dir():
        return Path(env)
    return via_file


def git_head(root: Path | None = None) -> str:
    """运行仓库的短 commit；失败返回空串（不抛异常）。"""
    root = root or project_root()
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        v = (out.stdout or "").strip()
        if out.returncode == 0 and v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return ""


def _key_files() -> list:
    root = project_root()
    rels = ["runs/agent/ui_app.py", "runs/agent/scheduler.py", "runs/agent/tools.py"]
    out = []
    for rel in rels:
        f = root / rel
        if f.exists():
            out.append(f)
    return out


def file_fingerprint() -> str:
    """关键文件内容指纹（git 不可用时的兜底）。"""
    h = hashlib.sha1()
    for f in _key_files():
        try:
            h.update(str(f).encode("utf-8", "replace"))
            h.update(f.read_bytes()[:8192])
        except OSError:
            continue
    return h.hexdigest()[:10]


def version(root: Path | None = None) -> str:
    """计算版本指纹；结果缓存。"""
    key = str(root or project_root())
    if key in _CACHE:
        return _CACHE[key]
    v = git_head(root) or ("file:" + file_fingerprint())
    _CACHE[key] = v
    return v


def deploy_site() -> str:
    """运行形态（win-remote / spark-local），失败返回 unknown。"""
    try:
        import json
        cfg = json.loads((project_root() / "config" / "deploy.json").read_text(encoding="utf-8-sig"))
        return str(cfg.get("site", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"


def describe() -> str:
    r = project_root()
    return f"AGENT_VERSION={version(r)} root={r} site={deploy_site()}"


AGENT_VERSION = version()


if __name__ == "__main__":
    print(describe())
