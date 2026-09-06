# -*- coding: utf-8 -*-
"""h3.quality — 质量看板（book-19 S10；全新建）。

职责：
  append(path, prompt_id)  — 产物完成时登记（probe_av 双流探测，与 PROBE 同源/择一）
  compare(a, b)           — ffmpeg SSIM 对比（需 ffmpeg；spark 侧使用）
  report()                — 汇总看板（logs/quality.jsonl）

默认日志：<项目根>/logs/quality.jsonl（逐行 JSON，append-only）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def _log_path(project_dir: Optional[Path] = None) -> Path:
    root = Path(project_dir) if project_dir else Path(__file__).resolve().parents[2]
    return root / "logs" / "quality.jsonl"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_fields(av: dict) -> dict:
    """probe_av 结果 → 记录字段（纯函数，可单测；bytes=av['size'] 同源择一）。"""
    return {
        "width": av.get("width"),
        "height": av.get("height"),
        "fps": av.get("fps"),
        "frames": av.get("frames"),
        "video_duration": av.get("video_duration"),
        "audio_codec": av.get("audio_codec"),
        "audio_channels": av.get("audio_channels"),
        "audio_duration": av.get("audio_duration"),
        "duration": av.get("duration"),
        "size": av.get("size"),
        "source": "probe_av",
    }


def append(path: str, prompt_id: str = "", project_dir: Optional[Path] = None,
           av: Optional[dict] = None) -> dict:
    """登记一条质量记录。av 缺省时用 postprocess.probe_av（失败抛 ValueError，调用方兜底）。"""
    from . import postprocess as _pp
    av = av or _pp.probe_av(str(path))
    rec = {"ts": _now(), "prompt_id": str(prompt_id or ""),
           "path": Path(path).name}
    rec.update(record_fields(av))
    f = _log_path(project_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load(project_dir: Optional[Path] = None) -> List[dict]:
    f = _log_path(project_dir)
    if not f.is_file():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            continue
    return out


def compare(a: str, b: str, timeout: int = 120) -> dict:
    """ffmpeg SSIM 对比（需 ffmpeg；返回 {ssim, cmd}；失败抛 ValueError）。"""
    cmd = ["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "ssim", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise ValueError("ssim 失败: " + (r.stderr or r.stdout or "")[-300:])
    ssim = None
    for ln in r.stderr.splitlines():
        if "All:" in ln:
            try:
                ssim = float(ln.strip().split("All:")[1].split()[0])
            except Exception:  # noqa: BLE001
                pass
            break
    if ssim is None:
        raise ValueError("ssim 输出不可解析")
    return {"ssim": ssim, "cmd": " ".join(cmd)}


def report(project_dir: Optional[Path] = None, limit: int = 20) -> dict:
    """汇总看板：总数/最近 limit 条/音频缺失计数。"""
    rows = load(project_dir)
    lacks_audio = [r for r in rows if not r.get("audio_codec")]
    return {
        "total": len(rows),
        "recent": rows[-limit:],
        "audio_missing_count": len(lacks_audio),
    }


def render(project_dir: Optional[Path] = None, limit: int = 20) -> str:
    d = report(project_dir, limit)
    lines = [f"== quality-report（总 {d['total']} 条；音频缺失 {d['audio_missing_count']}）=="]
    for r in reversed(d["recent"]):
        lines.append(
            "  %s  %s  %sx%s  dur=%s audio=%s size=%s  prompt=%s"
            % (r.get("ts", "?"), r.get("path", "?"),
               r.get("width"), r.get("height"), r.get("duration"),
               r.get("audio_codec") or "-", r.get("size"), r.get("prompt_id", "")[:8]))
    return "\n".join(lines)
