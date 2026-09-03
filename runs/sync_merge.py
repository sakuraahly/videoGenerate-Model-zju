#!/usr/bin/env python3
"""
sync_merge — 两端(Windows 本地 ↔ spark)文件“逐文件取新 + 显式冲突”合并工具。

协议背景（docs/deploy-modes.md §6）：
- 两端各自的 git 只记录本地历史（spark 不推 GitHub）；文件合并走本工具。
- 机器相关与运行产物不参与同步（EXCLUDE）；基线 .sync-state.json 两端各存一份。
- 判定（相对基线）：一端=基线另一端≠ → 单向改动/新增 → 自动；两端都≠基线 → 冲突，人工 --resolve。
- 删除不会自动执行：仅提示，由人确认后手动 rm 两端（防误删）。

用法（项目根）：
  python runs/sync_merge.py --status         # 分类清单（不传输）
  python runs/sync_merge.py --pull-auto      # 应用“仅远端较新/远端新增”到本地
  python runs/sync_merge.py --push-auto      # 应用“仅本地较新/本地新增”到远端
  python runs/sync_merge.py --resolve <rel> --from local|remote   # 冲突文件人工选边
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = ROOT.name
REMOTE = "spark"
STATE_NAME = ".sync-state.json"
EXCLUDE_TOP = {".git", ".test_tmp", "__pycache__", ".pytest_cache", "outputs", "logs"}
EXCLUDE_PREFIX = ("workflows/h3_",)
EXCLUDE_FILES = {
    STATE_NAME, ".sync-manifest.json", "config/llm.json", "config/deploy.json",
    "config/pipeline.json", "config/autosync.json", ".ai_brief.tmp.txt", "last_job.json",
    ".run.lock", ".tunnel.json",
}


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _scope(rel: str) -> bool:
    """纳入同步范围：任一段不在排除目录、非 workflows/h3_*、非机器文件。"""
    parts = rel.split("/")
    return (not any(p in EXCLUDE_TOP for p in parts)
            and not rel.startswith(EXCLUDE_PREFIX)
            and rel not in EXCLUDE_FILES)


def local_files() -> dict:
    out = {}
    for dirpath, _dirnames, filenames in os.walk(ROOT):
        rel_dir = Path(dirpath).relative_to(ROOT).as_posix()
        for fn in filenames:
            rel = f"{rel_dir}/{fn}" if rel_dir != "." else fn
            if _scope(rel):
                out[rel] = _h((Path(dirpath) / fn).read_bytes())
    return out


def remote_files() -> dict:
    """远端生成 sha256 清单到文件→scp 回本地→解析。"""
    _fd, _fp = tempfile.mkstemp(suffix=".syncraw")
    os.close(_fd)  # 立即关 fd，防 Windows 句柄占用
    tmp = Path(_fp)
    try:
        subprocess.run(["ssh", "-o", "BatchMode=yes", REMOTE,
                        f"cd ~/{NAME} && find . -type f -print0 | xargs -0 sha256sum | sort > ~/.sync.raw"],
                       check=False)
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"{REMOTE}:~/.sync.raw", str(tmp)],
                       check=False)
        subprocess.run(["ssh", "-o", "BatchMode=yes", REMOTE, "rm -f ~/.sync.raw"], check=False)
        out = {}
        for line in tmp.read_text(encoding="utf-8", errors="replace").splitlines():
            h, _, rel = line.strip().partition("  ")
            if not h or not rel:
                continue
            if rel.startswith("./"):
                rel = rel[2:]
            if _scope(rel):
                out[rel] = h
        return out
    finally:
        tmp.unlink(missing_ok=True)


def read_state() -> dict:
    p = ROOT / STATE_NAME
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def classify(local: dict, remote: dict, base: dict) -> dict:
    basef = base.get("files", {}) if isinstance(base, dict) else {}
    out = {"same": [], "conflict": [], "pull": [], "push": [], "delete_note": []}
    for rel in sorted(set(local) | set(remote)):
        l, r = local.get(rel), remote.get(rel)
        b = basef.get(rel)
        if l is not None and r is not None:
            if l == r:
                out["same"].append(rel)
            elif b is not None and l == b and r != b:
                out["pull"].append(rel)
            elif b is not None and r == b and l != b:
                out["push"].append(rel)
            else:
                out["conflict"].append(rel)
        elif l is None and r is not None:
            if b is None:
                out["pull"].append(rel + " (远端新增)")
            elif r == b:
                out["delete_note"].append(rel + " 本地删除（远端仍基线）：手动确认后两端删")
            else:
                out["conflict"].append(rel + " (远端改/本地删)")
        elif l is not None and r is None:
            if b is None:
                out["push"].append(rel + " (本地新增)")
            elif l == b:
                out["delete_note"].append(rel + " 远端删除（本地仍基线）：手动确认后两端删")
            else:
                out["conflict"].append(rel + " (本地改/远端删)")
    return out


def _run(cmd: list) -> None:
    subprocess.run(cmd, check=False)


def _push_apply(items: list) -> None:
    """本地较新/新增 → 打包发送到远端。"""
    rels = [i.split("  ")[0] for i in items]
    _fd, _fp = tempfile.mkstemp(suffix=".sp.tar")
    os.close(_fd)
    tmp = Path(_fp)
    try:
        with tarfile.open(tmp, "w") as tf:
            for rel in rels:
                p = ROOT / rel
                if p.exists():
                    tf.add(p, arcname=f"{NAME}/{rel}")
        _run(["scp", "-q", "-o", "BatchMode=yes", str(tmp), f"{REMOTE}:~/proj_merge.tar"])
        _run(["ssh", "-o", "BatchMode=yes", REMOTE,
              f"tar -xf ~/proj_merge.tar -C ~ && rm -f ~/proj_merge.tar"])
    finally:
        tmp.unlink(missing_ok=True)


def _pull_apply(items: list) -> None:
    """远端较新/新增 → 打包拉回本地。"""
    rels = [i.split("  ")[0] for i in items]
    q = " ".join(f"'{r}'" for r in rels)
    _run(["ssh", "-o", "BatchMode=yes", REMOTE,
          f"cd ~/{NAME} && tar --ignore-failed-read -cf ~/proj_merge.tar -- {q} 2>/dev/null; true"])
    _fd, _fp = tempfile.mkstemp(suffix=".sp.tar")
    os.close(_fd)
    tmp = Path(_fp)
    try:
        _run(["scp", "-q", "-o", "BatchMode=yes", f"{REMOTE}:~/proj_merge.tar", str(tmp)])
        if tmp.stat().st_size > 0:
            with tarfile.open(tmp) as tf:
                tf.extractall(ROOT)  # 包内顶层为 NAME/
        _run(["ssh", "-o", "BatchMode=yes", REMOTE, "rm -f ~/proj_merge.tar"])
    finally:
        tmp.unlink(missing_ok=True)


def make_base() -> None:
    """两端收敛后调用：以本地内容为准重建基线（假定 --status 无 conflict/pull/push 或已 auto 对齐）。"""
    write_state(local_files())


def write_state(base: dict) -> None:
    (ROOT / STATE_NAME).write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pull-auto", action="store_true")
    ap.add_argument("--push-auto", action="store_true")
    ap.add_argument("--make-base", action="store_true")
    ap.add_argument("--resolve", type=str, default="")
    ap.add_argument("--from", dest="src", choices=["local", "remote"], default="")
    args = ap.parse_args()

    local = local_files()
    remote = remote_files()
    base = read_state()
    c = classify(local, remote, base)

    if args.make_base:
        make_base()
        print("基线已重建（以本地当前内容为准；请确保两端已收敛或冲突已处理）。")
        return 0
    if args.resolve:
        rel = args.resolve.split("  ")[0]
        print(f"选边覆盖 {rel} <- {args.src}")
        if args.src == "local":
            _push_apply([rel])
        else:
            _pull_apply([rel])
        print("完成。随后 --status 应不再冲突；两端一致后可 --make-base 重建基线。")
        return 0
    if args.pull_auto:
        _pull_apply(c["pull"])
        print(f"已拉取远端较新/新增 {len(c['pull'])} 项。")
        return 0
    if args.push_auto:
        _push_apply(c["push"])
        print(f"已推送本地较新/新增 {len(c['push'])} 项。")
        return 0

    # status 默认
    print(f"一致 {len(c['same'])} · 远端较新(拉) {len(c['pull'])} · 本地较新(推) {len(c['push'])} · "
          f"冲突 {len(c['conflict'])} · 删除提示 {len(c['delete_note'])}")
    for lab, key in (("PULL 远端较新:", "pull"), ("PUSH 本地较新:", "push"),
                     ("CONFLICT(--resolve --from local|remote):", "conflict"),
                     ("删除提示(人工确认):", "delete_note")):
        if c[key]:
            print(lab)
            for x in c[key]:
                print("   ", x)
    print("无基线时(首次)请先单向对齐后用 --make-base；此后按基线三态合并。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
