#!/usr/bin/env python3
"""
sync_to_spark — 把整个项目目录同步到 spark（不含 .git 等），遵循传输约定。

约定：整目录外传一律不携带 .git（git 元数据走 GitHub）；本工具同步代码/配置/资产。

用法（在项目根，Windows python 运行）：
  python runs/sync_to_spark.py                # 增量：打包(排除) → scp 临时 tar → 远端解包到 ~/<项目名>
  python runs/sync_to_spark.py --clean        # 先删远端 ~/<项目名> 再全量传输
  python runs/sync_to_spark.py --dry-run      # 只打包并列出内容，不发 spark
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

EXCLUDE_DIRS = {".git", ".test_tmp", "__pycache__", ".pytest_cache"}
# 机器相关/产物/运行期文件：两端各自维护或运行期生成，不随整仓同步覆盖
# （deploy.json/llm.json 等两端本就不同；覆盖会把 spark-local 形态打回 win-remote）
EXCLUDE_FILES = {
    "config/deploy.json", "config/llm.json", "config/llm.json.bak",
    "config/pipeline.json", "config/transfer.json", "config/autosync.json",
    "config/upload_watch.json", ".sync-state.json", "last_job.json",
    ".tunnel.json", ".run.lock", ".ai_brief.tmp.txt", ".sync-manifest.json",
}
EXCLUDE_PREFIX = ("workflows/h3_",)
EXCLUDE_NAME = {"logs", "outputs"}


def _should_exclude(info: tarfile.TarInfo) -> bool:
    parts = Path(info.name).parts  # 形如 "<项目>/...."
    if len(parts) <= 1:
        return False
    rel_parts = parts[1:]
    if rel_parts[0] in EXCLUDE_DIRS:
        return True
    if rel_parts[0] in EXCLUDE_NAME:
        return True
    if rel_parts[0] in EXCLUDE_PREFIX:
        return True
    rel = "/".join(rel_parts)
    if rel in EXCLUDE_FILES:
        return True
    return False


def pack(project_root: Path) -> Path:
    """把项目打成 tar（排除 EXCLUDE_DIRS 顶层目录），返回临时文件路径。"""
    _fd, _fp = tempfile.mkstemp(suffix=".tar", prefix="proj2spark_")
    os.close(_fd)  # 立即关 fd，防 Windows 句柄占用导致后续删除失败
    tmp = Path(_fp)
    parent = project_root.parent
    name = project_root.name

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
        # 排除 .git/机器配置/产物/审计目录；两端文件语义见 EXCLUDE_*
        return None if _should_exclude(info) else info

    with tarfile.open(tmp, "w") as tf:
        tf.add(project_root, arcname=name, filter=_filter)
    return tmp


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="同步项目到 spark（不含 .git）")
    ap.add_argument("--target", default="spark")
    ap.add_argument("--clean", action="store_true", help="先删远端 ~/<项目名>")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pkg = pack(root)
    try:
        names = []
        with tarfile.open(pkg) as tf:
            names = tf.getnames()
        git_hits = [n for n in names if ".git" in Path(n).parts]
        print(f"打包: {len(names)} 项, {pkg.stat().st_size} B；含 .git 条目: {len(git_hits)}")
        if args.dry_run:
            print("(dry-run) 不发 spark。示例条目：")
            for n in names[:8]:
                print("  ", n)
            return 0
        if git_hits:
            print(f"[错误] 包里仍含 .git 条目: {git_hits[:3]}", file=sys.stderr)
            return 3

        if args.clean:
            print(f"删除远端 ~/{root.name} ...")
            subprocess.run(["ssh", "-o", "BatchMode=yes", args.target,
                            f"rm -rf ~/{root.name}"], check=False)
        print(f"scp 临时包 -> {args.target}:~/ ...")
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(pkg),
                        f"{args.target}:~/proj_sync.tar"], check=False)
        rc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.target,
             f"tar -xf ~/proj_sync.tar -C ~ && rm -f ~/proj_sync.tar && "
             f"echo OK && du -sh ~/{root.name}"], check=False)
        if rc.returncode != 0:
            print("[错误] 远端解包失败", file=sys.stderr)
            return 3
        print("完成。远端更新建议：ssh spark \"git -C ~/%s pull origin master\"" % root.name)
        return 0
    finally:
        try:
            pkg.unlink(missing_ok=True)
        except (PermissionError, OSError):
            pass  # Windows 偶发句柄占用，不影响传输结果


if __name__ == "__main__":
    sys.exit(main())
