#!/usr/bin/env python3
"""refimage — 参考素材池管理（把“ComfyUI 已保存图片 / 上传收件箱文件”用作
i2v / r2v / flf2v 的参考图）。

素材来源（三池）：
  [in]  ComfyUI input 目录（模板 LoadImage 直接可用的图库）
  [out] ComfyUI output 目录（历次 SaveImage/任务保存的图片产物，递归子目录）
  [up]  上传收件箱 uploads/（Open WebUI 上传，见 runs/h3/upload_watch.py）

命令：
  list                     列出三池可作参考的图片/视频（含 id、来源、路径）
                           [--pool in|up|out] [--name 关键字] [--all] [--limit N]
  promote --name <sel>     把选中的素材复制进 ComfyUI input（供 LoadImage 使用）
                           <sel> = list 输出的 id（如 up:0）或文件名或绝对路径
                           [--as <filename>] 指定进入 input 后的文件名
  use --name <sel> --stage <i2v|r2v|flf2v> [--slot N]
                           设置参考图：把该 stage 本地镜像模板的第 N 个 LoadImage
                           指向选中素材（r2v 有两个槽位 0/1；不带 --slot 默认槽 0）。
  use --info --stage r2v   查看模板的参考图槽位映射（不改动）
  use --undo               恢复本地镜像模板（git checkout 还原，仅适用已入库镜像）
  where                    打印三个池目录位置

形态隔离：以 config/deploy.json 为准。spark-local 在本机直接操作；win-remote
（本机仓库 + 隧道）时自动把本命令经 `ssh spark` 委托到 spark 上的同一仓库执行
（参考素材与 ComfyUI 都在 spark，符合“spark-local 用 spark 文件夹、win-remote
经 ssh 通道”的约定）。

示例：
  python runs/h3/refimage.py list --pool up
  python runs/h3/refimage.py list --name 沙朗
  python runs/h3/refimage.py promote --name up:0
  python runs/h3/refimage.py use --name up:0 --stage r2v --slot 0   # 角色参考
  python runs/h3/refimage.py use --name up:1 --stage r2v --slot 1   # 第二张参考
  python runs/h3/refimage.py use --info --stage r2v
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
    """三池扫描 → [{"pool","name","full","size","mtime","kind"}]。

    池显示顺序：up（上传收件箱，最近最相关）→ in（ComfyUI input）→ out（ComfyUI
    output 历史产物）；input/uploads 均**递归**扫描（upload_watch 会把图片镜像到
    input/user_uploads/ 子目录，顶层扫描会漏）。
    """
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

    for d, pool in ((dirs["uploads"], "up"), (dirs["input"], "in")):
        if os.path.isdir(d):
            for dp, _dn, fn in os.walk(d):
                for name in sorted(fn):
                    add(pool, os.path.join(dp, name))
    if os.path.isdir(dirs["output"]):
        for dp, _dn, fn in os.walk(dirs["output"]):
            for name in sorted(fn):
                add("out", os.path.join(dp, name))
    pool_order = {"up": 0, "in": 1, "out": 2}
    out.sort(key=lambda r: (pool_order[r["pool"]], -r["mtime"]))
    return out


def _filter_rows(rows: list, pool: str = "", name: str = "", kinds=(("image", "video"),),
                 show_other: bool = False) -> list:
    res = rows
    if pool:
        res = [r for r in res if r["pool"] == pool]
    if name:
        res = [r for r in res if name.lower() in r["name"].lower()]
    if not show_other:
        res = [r for r in res if r["kind"] != "other"]
    return res


def cmd_list(dirs: dict, show_other: bool = False, pool: str = "",
             name: str = "", limit: int = 25) -> int:
    rows = _filter_rows(_rows(dirs), pool=pool, name=name, show_other=show_other)
    print(f"素材池位置：{json.dumps(dirs, ensure_ascii=False)}")
    print(f"过滤：池={pool or '全部'} 名称含={name or '-'}（默认仅图片，--all 含视频/其它）")
    print(f"{'id':<10}{'池':<5}{'类型':<7}{'大小':>10}  {'名称'}")
    pools = []
    for r in rows:
        if r["pool"] not in pools:
            pools.append(r["pool"])
    counts = {p: 0 for p in pools}
    omitted = 0
    for r in rows:
        counts[r["pool"]] += 1
        idx = counts[r["pool"]] - 1
        if idx < limit:
            print(f"{r['pool']}:{idx:<8}{r['pool']:<5}{r['kind']:<7}{r['size']:>10}  {r['name']}")
        else:
            omitted += 1
    if omitted:
        print(f"… 省略 {omitted} 项（每池最多 {limit} 行；可用 --pool/--name 过滤、--limit 调大）")
    print(f"共 {len(rows)} 项（各池计数 {counts}）。用法：promote --name <id|文件名>；"
          f"use --name <id|文件名> --stage r2v [--slot 0|1]")
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


def template_slots(tpl: Path) -> list:
    """返回模板中 LoadImage 槽位：[(槽位序号, 当前图名), ...]（按节点顺序）。"""
    data = json.loads(tpl.read_text(encoding="utf-8-sig"))
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        raise ValueError(f"模板不是 UI 格式: {tpl}")
    slots = []
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "LoadImage":
            vals = n.get("widgets_values") or []
            slots.append((len(slots), str(vals[0]) if vals else ""))
    return slots


def _print_slots(tpl: Path) -> None:
    try:
        slots = template_slots(tpl)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return
    print(f"模板 {tpl.name} 参考图槽位（共 {len(slots)} 个，0 起编号）：")
    for idx, cur in slots:
        print(f"  slot {idx}: {cur or '(空)'}")


def cmd_use(dirs: dict, sel: str, stage: str, targets: str, slot: int,
            undo: bool, info: bool) -> int:
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
    if info:
        _print_slots(tpl)
        return 0
    try:
        slots = template_slots(tpl)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 3
    if not slots:
        print(f"[错误] 模板 {tpl.name} 中没有 LoadImage 节点", file=sys.stderr)
        return 3
    if slot is not None:
        if slot < 0 or slot >= len(slots):
            print(f"[错误] slot {slot} 越界（模板共 {len(slots)} 个槽位: 0..{len(slots)-1}）；"
                  f"用 use --info 查看", file=sys.stderr)
            return 3
        targets = f"slot:{slot}"

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
    # 2) 改写本地镜像模板的 LoadImage（--slot N 精确槽位 / --first 第一个 / --all-loads 全部）
    data = json.loads(tpl.read_text(encoding="utf-8-sig"))
    nodes = data.get("nodes")
    patched = 0
    for n in nodes:
        if not (isinstance(n, dict) and n.get("type") == "LoadImage"):
            continue
        if targets.startswith("slot:"):
            if patched != int(targets.split(":", 1)[1]):
                patched += 1
                continue
        vals = n.get("widgets_values") or []
        if not vals:
            vals = [""]
            n["widgets_values"] = vals
        vals[0] = name
        patched += 1
        if targets in ("first",) or targets.startswith("slot:"):
            break
    if patched == 0:
        print(f"[错误] 未能定位要修改的 LoadImage 槽位", file=sys.stderr)
        return 3
    tpl.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已把 {stage} 模板 {tpl.name} 的 LoadImage 指向: {name}（target={targets}）")
    _print_slots(tpl)
    print("提示：槽位提示词由 prompts/workflows/ 对应文件控制；恢复模板请执行 use --undo。")
    _log(f"use stage={stage} image={name} targets={targets}")
    return 0


def cmd_where(dirs: dict) -> int:
    for k, v in dirs.items():
        print(f"{k:<8}: {v}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="参考素材池管理（ComfyUI 已保存图 / 上传收件箱）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true", help="含视频/其它类型（默认仅图片）")
    p_list.add_argument("--pool", default="", choices=["in", "up", "out", ""],
                        help="只看某个池")
    p_list.add_argument("--name", default="", help="按文件名包含过滤")
    p_list.add_argument("--limit", type=int, default=25, help="每池最多显示行数")
    p_prom = sub.add_parser("promote")
    p_prom.add_argument("--name", required=True)
    p_prom.add_argument("--as", dest="as_name", default="")
    p_use = sub.add_parser("use")
    p_use.add_argument("--name", default="")
    p_use.add_argument("--stage", default="i2v",
                       choices=["i2v", "r2v", "flf2v"])
    p_use.add_argument("--slot", type=int, default=None,
                       help="精确指定参考图槽位（0 起，如 r2v 有 0/1 两个）；"
                            "用 use --info 查看槽位映射")
    p_use.add_argument("--first", dest="targets", action="store_const", const="first",
                       default="first")
    p_use.add_argument("--all-loads", dest="targets", action="store_const", const="all")
    p_use.add_argument("--undo", action="store_true", help="git 还原模板")
    p_use.add_argument("--info", action="store_true",
                       help="只打印模板参考图槽位映射，不改动")
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
        return cmd_list(dirs, show_other=args.all, pool=args.pool,
                        name=args.name, limit=args.limit)
    if args.cmd == "promote":
        return cmd_promote(dirs, args.name, args.as_name)
    if args.cmd == "use":
        if args.info:
            return cmd_use(dirs, "", args.stage, "first", None, False, True)
        if not args.undo and not args.name:
            print("use 需要 --name <id|文件名> 或 --undo 或 --info", file=sys.stderr)
            return 3
        return cmd_use(dirs, args.name, args.stage, args.targets,
                       args.slot, args.undo, False)
    if args.cmd == "where":
        return cmd_where(dirs)
    return 0


def shlex_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(main())
