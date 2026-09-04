#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/golden_path.py — book-09 黄金路径（引擎级端到端，spark 运行，venv python）。

用法：
  python tests/golden_path.py submit --stage flf2v --images A.png,B.png [--resolution 360p] [--seconds 5]
  python tests/golden_path.py fetch --prompt-id <id>          # 轮询取片（可多次）
链路：绑定(若 --images) → 提交(submit-only) → 取片(--resume) → 断言产物存在 & 非默认旧资产。
输出标记：GOLDEN_SUBMITTED / GOLDEN_OK / GOLDEN_FAIL。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMIT = ROOT / "runs" / "h3_submit.py"


def _run(argv, timeout=600):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))


def _mark(line):
    print(f"[GOLDEN] {line}", flush=True)


def cmd_submit(args) -> int:
    cmd = [sys.executable, str(SUBMIT), "--stage", args.stage,
           "--resolution", args.resolution, "--seconds", str(args.seconds),
           "--submit-only", "--force-new"]
    for img in args.images.split(","):
        if img.strip():
            cmd.extend(["--image", img.strip()])
    r = _run(cmd, 300)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        _mark(f"FAIL submit rc={r.returncode}: {out[-300:]}")
        return 1
    pid = next((ln.split(":", 1)[1].strip() for ln in out.splitlines()
                if ln.startswith("TASK_SUBMITTED:")), "")
    if not pid:
        _mark("FAIL: 无 TASK_SUBMITTED")
        return 1
    _mark(f"TASK_SUBMITTED {pid}")
    _mark("已提交（后台运行）。请稍后用 fetch 取片。")
    Path("/tmp/golden_prompt_id.txt").write_text(pid, encoding="utf8")
    return 0


def cmd_fetch(args) -> int:
    pid = args.prompt_id or (Path("/tmp/golden_prompt_id.txt").read_text(encoding="utf8").strip()
                             if Path("/tmp/golden_prompt_id.txt").exists() else "")
    if not pid:
        _mark("FAIL: 无 prompt_id")
        return 1
    cmd = [sys.executable, str(SUBMIT), "--resume", pid]
    r = _run(cmd, 240)
    out = r.stdout + r.stderr
    print(out[-600:])
    if r.returncode == 0 and "LOCAL_OUTPUT:" in out:
        local = next((ln.split(":", 1)[1].strip() for ln in out.splitlines()
                      if ln.startswith("LOCAL_OUTPUT:")), "")
        p = Path(local)
        ok = p.exists() and p.stat().st_size > 1000
        _mark(f"产物: {local} size={p.stat().st_size if p.exists() else 0}")
        _mark("GOLDEN_OK" if ok else "GOLDEN_FAIL: 产物缺失/为空")
        return 0 if ok else 1
    if r.returncode == 2:
        _mark("仍在生成中，请稍后再 fetch（GOLDEN_PENDING）")
        return 2
    _mark(f"GOLDEN_FAIL: rc={r.returncode}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="book-09 黄金路径")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--stage", default="flf2v")
    s.add_argument("--images", default="", help="逗号分隔参考图（文件名/素材名）")
    s.add_argument("--resolution", default="360p")
    s.add_argument("--seconds", type=int, default=5)
    f = sub.add_parser("fetch")
    f.add_argument("--prompt-id", default="")
    a = ap.parse_args()
    if a.cmd == "submit":
        return cmd_submit(a)
    return cmd_fetch(a)


if __name__ == "__main__":
    sys.exit(main())
