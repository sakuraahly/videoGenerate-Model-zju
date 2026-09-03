#!/usr/bin/env python3
"""upload_watch — Open WebUI 上传收件箱看门狗（spark 侧运行）。

Open WebUI（端口 3000）的对话界面支持上传图片/视频等附件，其文件落在 Open WebUI
的 data 目录 uploads 下。本看门狗周期扫描该目录，把**新文件**归档进项目
uploads/（按日期子目录、去重），图片类同时镜像一份到 ComfyUI input/user_uploads/
（供 i2v/r2v/flf2v 的 LoadImage 直接选用），并记录 jsonl 流水
（uploads/log.jsonl）。随后可用 runs/h3/refimage.py list（up 池）查看，或
promote/use 把它作为参考图。

命令：
  python3 runs/h3/upload_watch.py status   # 查看开关/目录/已归档数量
  python3 runs/h3/upload_watch.py once     # 立即扫描一轮（可加 --dir 指定数据目录）
  python3 runs/h3/upload_watch.py watch    # 前台循环（--interval 秒，Ctrl+C 退出）
  python3 runs/h3/upload_watch.py daemon   # tmux/后台由调用方包装时使用（=watch）

配置 config/upload_watch.json（两端各自维护）：
  {"enabled": true, "interval": 30,
   "openwebui_data_dir": "~/.open-webui",      # Open WebUI data 目录(含 uploads/)
   "keep_originals": true}
启用示例（tmux 会话 upload-watch）：
  tmux new-session -d -s upload-watch \
    'source ~/qwen-agent-venv/bin/activate 2>/dev/null; cd ~/videoGenerate-Model-zju \
     && python3 runs/h3/upload_watch.py watch --interval 30 2>&1 | tee ~/upload-watch.log'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CFG = ROOT / "config" / "upload_watch.json"
ARCHIVE = ROOT / "uploads"
LOGJSON = ARCHIVE / "log.jsonl"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VID_EXT = {".mp4", ".webm", ".mov", ".mkv", ".gif"}

DEFAULT = {"enabled": True, "interval": 30,
           # 实测：本机 pip 版 Open WebUI 数据目录在 ~/.cache/open-webui
           # （首次上传前 uploads/ 子目录可能尚不存在，属正常）
           "openwebui_data_dir": os.path.expanduser("~/.cache/open-webui"),
           "keep_originals": True}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_cfg() -> dict:
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
        return {**DEFAULT, **cfg}
    except Exception:  # noqa: BLE001
        return dict(DEFAULT)


def save_cfg(cfg: dict) -> None:
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _seen() -> set:
    if not LOGJSON.exists():
        return set()
    seen = set()
    try:
        for line in LOGJSON.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                seen.add(json.loads(line)["sha"])
            except Exception:  # noqa: BLE001
                continue
    except OSError:
        pass
    return seen


def _record(entry: dict) -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    with open(LOGJSON, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _comfy_input_mirror() -> Path:
    comfy = "~/ai/ComfyUI"
    try:
        env = json.loads((ROOT / "config" / "environment.json").read_text(encoding="utf-8-sig"))
        comfy = env.get("remote_comfyui_dir") or comfy
    except Exception:  # noqa: BLE001
        pass
    return Path(comfy.replace("~", str(Path.home()))) / "input" / "user_uploads"


def scan_once(data_dir: str, dry_run: bool = False) -> tuple:
    """扫描 Open WebUI uploads 目录并归档新文件；返回 (新增数, 跳过数, 错误)。"""
    upload_dir = Path(data_dir).expanduser() / "uploads"
    if not upload_dir.is_dir():
        return (0, 0, f"Open WebUI uploads 目录不存在: {upload_dir}")
    seen = _seen()
    mirror = _comfy_input_mirror()
    added = skipped = 0
    errors = []
    for p in sorted(upload_dir.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if sha in seen:
            skipped += 1
            continue
        ext = p.suffix.lower()
        kind = "video" if ext in VID_EXT else ("image" if ext in IMG_EXT else "other")
        day = datetime.now().strftime("%Y%m%d")
        dst_dir = ARCHIVE / day
        dst = dst_dir / f"{sha[:8]}_{p.name}"
        if not dry_run:
            try:
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
                if kind == "image":
                    mirror.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, mirror / p.name)
                _record({"ts": _now(), "sha": sha, "src": str(p),
                         "archived": str(dst), "kind": kind,
                         "mirrored_input": kind == "image"})
            except OSError as e:
                errors.append(f"{p.name}: {e}")
                continue
        added += 1
        print(f"[upload_watch] {kind}: {p.name} -> {dst}")
    print(f"[upload_watch] 本轮新增 {added}，跳过 {skipped}"
          + (f"，错误 {len(errors)}" if errors else ""))
    return added, skipped, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Open WebUI 上传收件箱看门狗")
    ap.add_argument("cmd", choices=["status", "once", "watch", "daemon"])
    ap.add_argument("--dir", default=None, help="Open WebUI data 目录覆盖（测试用）")
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_cfg()
    if args.dir:
        cfg["openwebui_data_dir"] = args.dir
    interval = args.interval or int(cfg.get("interval") or 30)

    if args.cmd == "status":
        print(f"enabled: {cfg['enabled']}   interval: {interval}s")
        print(f"Open WebUI data: {cfg['openwebui_data_dir']}")
        print(f"归档目录: {ARCHIVE}  流水: {LOGJSON}")
        if ARCHIVE.is_dir():
            print(f"已归档文件数: {sum(1 for _ in ARCHIVE.rglob('*') if _.is_file() and 'log.jsonl' != _.name)}")
        return 0

    if args.cmd == "once":
        scan_once(str(cfg["openwebui_data_dir"]), dry_run=args.dry_run)
        return 0

    # watch / daemon
    print(f"[upload_watch] watch 启动（interval={interval}s，Ctrl+C 退出）")
    try:
        sys.stdout.reconfigure(line_buffering=True)  # tee/管道下日志即时可见
    except Exception:  # noqa: BLE001
        pass
    try:
        while True:
            try:
                scan_once(str(cfg["openwebui_data_dir"]))
            except Exception as e:  # noqa: BLE001
                print(f"[upload_watch] 扫描异常: {e}", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[upload_watch] 已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
