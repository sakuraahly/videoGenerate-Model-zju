#!/usr/bin/env python3
"""refimage — 参考素材池管理（把“ComfyUI 已保存图片 / 上传收件箱文件”用作
i2v / r2v / flf2v 的参考图）。

素材来源（三池）：
  [in]  ComfyUI input 目录（模板 LoadImage 直接可用的图库）
  [out] ComfyUI output 目录（历次 SaveImage/任务保存的图片产物，递归子目录）
  [up]  上传收件箱 uploads/（Open WebUI 上传，见 runs/h3/upload_watch.py）

命令：
  list                     列出三池可作参考的图片/视频（含 id、来源、路径）
  promote --name <sel>     把选中的素材复制进 ComfyUI input（供 LoadImage 使用）
                           <sel> = list 输出的 id（如 out:3）或文件名或绝对路径
                           [--as <filename>] 指定进入 input 后的文件名
  use --name <sel> --stage <i2v|r2v|flf2v> [--first|--all]
                           promote + 把该 stage 本地镜像模板里 LoadImage 的图片名
                           改写为选中素材（--first 只改第一个 LoadImage；默认 first）
  use --undo               恢复本地镜像模板（git checkout 还原，仅适用已入库镜像）
  where                    打印三个池目录位置

形态隔离：以 config/deploy.json 为准。spark-local 在本机直接操作；win-remote
（本机仓库 + 隧道）时自动把本命令经 `ssh spark` 委托到 spark 上的同一仓库执行
（参考素材与 ComfyUI 都在 spark，符合“spark-local 用 spark 文件夹、win-remote
经 ssh 通道”的约定）。

示例：
  python runs/h3/refimage.py list
  python runs/h3/refimage.py promote --name out:0
  python runs/h3/refimage.py use --name up:hero.png --stage r2v --first
  python runs/h3/refimage.py use --undo
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # 项目根
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VID_EXT = {".mp4", ".webm", ".mov", ".mkv", ".gif"}


def _log(text: str) -> None:
    try:
        runs_dir = str(ROOT / "runs")
        if runs_dir not in sys.path:
            sys.path.insert(0, runs_dir)
        from h3 import logutil
        logutil.ensure_run_log(ROOT, "refimage")
        logutil.log_event("refimage", text)
    except Exception:  # noqa: BLE001
        pass


def _site() -> str:
    try:
        dep = json.loads((ROOT / "config" / "deploy.json").read_text(encoding="utf-8-sig"))
        return str(dep.get("site") or "win-remote")
    except Exception:  # noqa: BLE001
        return "win-remote"


def comfy_dirs() -> dict:
    """ComfyUI 目录：优先 config/environment.json，缺省 ~/ai/ComfyUI。"""
    comfy = "~/ai/ComfyUI"
    try:
        env = json.loads((ROOT / "config" / "environment.json").read_text(encoding="utf-8-sig"))
        comfy = env.get("remote_comfyui_dir") or comfy
    except Exception:  # noqa: BLE001
        pass
    home = str(Path.home())
    comfy = comfy.replace("~", home)
    return {"comfy": comfy,
            "input": os.path.join(comfy, "input"),
            "output": os.path.join(comfy, "output"),
            "uploads": str(ROOT / "uploads")}


def _rows(dirs: dict) -> list:
    """三池扫描 → [{"pool","file","name","size","mtime","full"}]，按池分组排序。"""
    out = []
    seen = set()

    def add(pool: str, full: str) -> None:
        p = Path(full)
        if not p.is_file() or p.name.startswith("."):
            return
        key = f"{pool}:{p.name}:{p.stat().st_size}"
        if key in seen:
            return
        seen.add(key)
        ext = p.suffix.lower()
        kind = "video" if ext in VID_EXT else ("image" if ext in IMG_EXT else "other")
        out.append({"pool": pool, "name": p.name, "full": str(p),
                    "size": p.stat().st_size, "mtime": p.stat().st_mtime,
                    "kind": kind})

    for d, pool in ((dirs["input"], "in"), (dirs["uploads"], "up")):
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                add(pool, os.path.join(d, name))
    # ComfyUI output：递归收集图片（保存的图片产物可能带子目录）
    if os.path.isdir(dirs["output"]):
        for dp, _dn, fn in os.walk(dirs["output"]):
            for name in sorted(fn):
                add("out", os.path.join(dp, name))
    out.sort(key=lambda r: (r["pool"], r["mtime"]), reverse=True)
    return out


def cmd_list(dirs: dict, show_other: bool = False) -> int:
    rows = _rows(dirs)
    print(f"素材池位置：{json.dumps(dirs, ensure_ascii=False)}")
    print(f"{'id':<10}{'池':<5}{'类型':<7}{'大小':>10}  {'名称'}")
    for i, r in enumerate(rows):
        if r["kind"] == "other" and not show_other:
            continue
        print(f"{r['pool']}:{i:<8}{r['pool']:<5}{r['kind']:<7}{r['size']:>10}  {r['name']}")
    print(f"\n共 {len(rows)} 项（--all 含其它类型）。用法：promote --name <id|文件名>；"
          f"use --name <id|文件名> --stage r2v")
    _log("list")
    return 0


def _resolve_sel(rows: list, sel: str) -> dict:
    """sel 支持：池:序号（如 out:3）、裸文件名、绝对/相对路径。找不到抛 ValueError。"""
    if ":" in sel and sel.split(":", 1)[0] in ("in", "out", "up"):
        pool, idx = sel.split(":", 1)
        hits = [r for r in rows if r["pool"] == pool]
        try:
            return hits[int(idx)]
        except (ValueError, IndexError):
            raise ValueError(f"序号越界: {sel}")
    for r in rows:
        if r["name"] == sel or r["full"] == sel:
            return r
    p = Path(sel).expanduser()
    if p.is_file():
        for r in rows:
            if os.path.abspath(r["full"]) == os.path.abspath(str(p)):
                return r
        return {"pool": "file", "name": p.name, "full": str(p),
                "size": p.stat().st_size, "mtime": p.stat().st_mtime,
                "kind": "image" if p.suffix.lower() in IMG_EXT else "other"}
    raise ValueError(f"找不到素材: {sel}（先用 list 查看 id/文件名）")


def cmd_promote(dirs: dict, sel: str, as_name: str = "") -> int:
    rows = _rows(dirs)
    try:
        r = _resolve_sel(rows, sel)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        _log(f"err {e}")
        return 3
    if r["kind"] not in ("image", "video"):
        print(f"[错误] {r['name']} 不是图片/视频", file=sys.stderr)
        return 3
    name = as_name or r["name"]
    dst = os.path.join(dirs["input"], name)
    if os.path.abspath(dst) == os.path.abspath(r["full"]):
        print(f"已在 input 中：{dst}")
        return 0
    try:
        shutil.copy2(r["full"], dst)
    except OSError as e:
        print(f"[错误] 复制失败: {e}", file=sys.stderr)
        _log(f"err promote {r['full']} -> {dst}: {e}")
        return 3
    print(f"已放入 ComfyUI input: {dst}")
    _log(f"promote name={name} from={r['full']}")
    return 0


def _stage_template(stage: str) -> Path:
    if stage == "flf2v":
        return ROOT / "workflows" / "remote_workflows" / "video_minimax_h3_flf2v.json"
    return ROOT / "workflows" / "remote_workflows" / f"video_minimax_h3_{stage}.json"


def cmd_use(dirs: dict, sel: str, stage: str, targets: str, undo: bool) -> int:
    tpl = _stage_template(stage)
    if not tpl.exists():
        print(f"[错误] 该 stage 无本地镜像模板: {tpl}", file=sys.stderr)
        return 3
    if undo:
        r = subprocess.run(["git", "-C", str(ROOT), "checkout", "--", str(tpl)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print(f"已还原模板: {tpl.name}")
            _log(f"undo template={tpl.name}")
            return 0
        print(f"[错误] 还原失败（模板可能未入库/有本地新增）: {r.stderr[:200]}", file=sys.stderr)
        return 3
    rows = _rows(dirs)
    try:
        r = _resolve_sel(rows, sel)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 3
    if r["kind"] != "image":
        print(f"[错误] 参考图需为图片: {r['name']}", file=sys.stderr)
        return 3
    # 1) promote 到 input
    name = r["name"]
    dst = os.path.join(dirs["input"], name)
    if os.path.abspath(dst) != os.path.abspath(r["full"]):
        shutil.copy2(r["full"], dst)
    # 2) 改写本地镜像模板的全部/首个 LoadImage
    data = json.loads(tpl.read_text(encoding="utf-8-sig"))
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if nodes is None:
        print(f"[错误] 模板不是 UI 格式: {tpl}", file=sys.stderr)
        return 3
    patched = 0
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "LoadImage":
            vals = n.get("widgets_values") or []
            if vals:
                vals[0] = name
                patched += 1
                if targets == "first":
                    break
    if patched == 0:
        print(f"[错误] 模板 {tpl.name} 中没有 LoadImage 节点", file=sys.stderr)
        return 3
    tpl.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已把 {stage} 模板 {tpl.name} 的 {patched} 个 LoadImage 指向: {name}")
    print("提示：槽位提示词由 prompts/workflows/ 对应文件控制；恢复模板请执行 use --undo。")
    _log(f"use stage={stage} image={name} patched={patched} targets={targets}")
    return 0


def cmd_where(dirs: dict) -> int:
    for k, v in dirs.items():
        print(f"{k:<8}: {v}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="参考素材池管理（ComfyUI 已保存图 / 上传收件箱）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true", help="含其它类型文件")
    p_prom = sub.add_parser("promote")
    p_prom.add_argument("--name", required=True)
    p_prom.add_argument("--as", dest="as_name", default="")
    p_use = sub.add_parser("use")
    p_use.add_argument("--name", default="")
    p_use.add_argument("--stage", default="i2v",
                       choices=["i2v", "r2v", "flf2v"])
    p_use.add_argument("--first", dest="targets", action="store_const", const="first",
                       default="first")
    p_use.add_argument("--all-loads", dest="targets", action="store_const", const="all")
    p_use.add_argument("--undo", action="store_true")
    sub.add_parser("where")
    args = ap.parse_args(argv)

    dirs = comfy_dirs()
    # win-remote：素材与 ComfyUI 都在 spark → 委托 spark 上的同一仓库执行本命令
    if args.cmd != "undo-delegate" and _site() == "win-remote" \
            and not os.environ.get("REFIMAGE_DELEGATED"):
        argv_enc = [args.cmd] + sys.argv[sys.argv.index(args.cmd) + 1:]
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "spark",
             f"cd ~/videoGenerate-Model-zju && REFIMAGE_DELEGATED=1 python3 "
             f"runs/h3/refimage.py {' '.join(shlex_quote(a) for a in argv_enc)}"],
            capture_output=True, text=True, timeout=180)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode if r.returncode in (0, 2, 3) else 3

    if args.cmd == "list":
        return cmd_list(dirs, show_other=args.all)
    if args.cmd == "promote":
        return cmd_promote(dirs, args.name, args.as_name)
    if args.cmd == "use":
        if not args.undo and not args.name:
            print("use 需要 --name <id|文件名> 或 --undo", file=sys.stderr)
            return 3
        return cmd_use(dirs, args.name, args.stage, args.targets, args.undo)
    if args.cmd == "where":
        return cmd_where(dirs)
    return 0


def shlex_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(main())
