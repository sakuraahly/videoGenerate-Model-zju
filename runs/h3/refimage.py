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
                           指向选中素材并自动启用/接线（r2v 节点 ref_images 为
                           autogrow，默认 8 槽 0..7，未用槽位处于禁用占位态；
                           不带 --slot 默认槽 0）。
  use --info --stage r2v   查看模板的参考图槽位映射（含禁用态，不改动）
  grow --stage r2v --total 12
                           把模板参考槽位扩到任意数量（自动补 ref_image_N 行 +
                           禁用 LoadImage 占位；配合 use --slot 使用）
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
  python runs/h3/refimage.py use --name up:2 --stage r2v --slot 2   # 第三张…（自动启用）
  python runs/h3/refimage.py grow --stage r2v --total 12            # 扩到 12 槽
  python runs/h3/refimage.py use --info --stage r2v
  python runs/h3/refimage.py use --undo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
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
    跳过 _quarantine/ 目录和 <1KB 图片（疑似无效）。
    """
    out = []
    seen = set()

    def add(pool: str, full: str) -> None:
        p = Path(full)
        if not p.is_file() or p.name.startswith("."):
            return
        if "_quarantine" in p.parts:
            return
        key = f"{pool}:{p.name}:{p.stat().st_size}"
        if key in seen:
            return
        seen.add(key)
        ext = p.suffix.lower()
        kind = "video" if ext in VID_EXT else ("image" if ext in IMG_EXT else "other")
        st = p.stat()
        if kind == "image" and st.st_size < 1024:
            return
        out.append({"pool": pool, "name": p.name, "full": str(p),
                    "size": st.st_size, "mtime": st.st_mtime,
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


def _load_batch_map() -> dict:
    """加载 log.jsonl 的 sha→batch_id 映射（带 mtime+size 缓存）。"""
    log_path = ROOT / "uploads" / "log.jsonl"
    try:
        st = log_path.stat()
        key = (st.st_mtime, st.st_size)
    except OSError:
        return {}
    if hasattr(_load_batch_map, '_cache') and _load_batch_map._cache_key == key:
        return dict(_load_batch_map._cache)
    mapping = {}
    try:
        for line in log_path.read_text(encoding='utf-8').splitlines():
            try:
                d = json.loads(line)
                sha = d.get('sha', '')
                bid = d.get('batch_id', '')
                cid = str(d.get('cid', '') or '')
                if sha:
                    entry = mapping.setdefault(sha, {"bid": bid or '', "cids": set()})
                    entry["bid"] = bid or entry.get("bid", '')
                    if cid:
                        entry["cids"].add(cid)
            except Exception:
                continue
    except OSError:
        pass
    for e in mapping.values():
        e["cids"] = set(e["cids"])
    _load_batch_map._cache = mapping
    _load_batch_map._cache_key = key
    return dict(mapping)


def _get_row_meta(row: dict, batch_map: dict) -> dict:
    """从 row 的 name 前缀 sha 提取 {'bid','cids'}（book-05：会话归属；同图上多个会话）。"""
    name = row.get('name', '')
    parts = name.split('_', 1)
    if len(parts) >= 2 and len(parts[0]) == 8:
        for sha, meta in batch_map.items():
            if sha.startswith(parts[0]):
                return {"bid": meta.get("bid", ""), "cids": set(meta.get("cids", set()))}
    return {"bid": "", "cids": set()}


def _filter_by_session(rows: list, batch_map: dict, session: str) -> list:
    """只保留本会话（cid）的素材行（book-05 资源隔离核心）。"""
    return [r for r in rows if session in _get_row_meta(r, batch_map).get('cids')]


_LITERAL_SESSION = {'current', 'this', 'latest', 'now', '本会话'}


def normalize_session(value, current: str = '') -> str:
    """归一化 session 取值（book-05 优化1）：

    - 空/字面词(current/this/latest/now/本会话) → 用 current（CURRENT_SESSION）；
    - current 为空时返回 'all'（无会话上下文）；
    - 'all' 原样；其余按字面 cid 返回。
    """
    v = str(value or '').strip()
    if not v or v.lower() in _LITERAL_SESSION:
        return (current or '').strip() or 'all'
    return v


def _dedupe_by_prefix(rows: list) -> tuple:
    """同 sha8 前缀（同文件多池镜像）只保留首个，返回 (去重后的行, 镜像提示列表)。"""
    seen = set()
    kept = []
    notes = []
    for r in rows:
        parts = r.get('name', '').split('_', 1)
        prefix = parts[0] if len(parts) >= 2 and len(parts[0]) == 8 else r.get('name', '')
        if prefix in seen:
            notes.append(f"{r.get('pool')}:{r.get('name')} 为同图镜像，未重复列出")
            continue
        seen.add(prefix)
        kept.append(r)
    return kept, notes


def cmd_list(dirs: dict, show_other: bool = False, pool: str = "",
             name: str = "", limit: int = 25, batch: str = "",
             recent: int = 0, session: str = "", scope_all: bool = False) -> int:
    rows = _filter_rows(_rows(dirs), pool=pool, name=name, show_other=show_other)
    batch_map = _load_batch_map()

    if session:
        # book-05：默认只看本会话素材（上传时记录 cid）；其他历史产物需 --scope-all
        sel = _filter_by_session(rows, batch_map, session)
        if not sel:
            print(f"本会话 {session} 暂无可用素材（上传后自动归档到本会话；如需全部素材请用 --scope-all）")
            return 0
        sel, notes = _dedupe_by_prefix(sel)  # 优化2：up/in 镜像只列一次
        rows = sel
        print(f"会话过滤: {session}（{len(rows)} 项，按时间倒序；其他历史产物需 --scope-all）")
        for n in notes[:8]:
            print(f"  [注] {n}")
    elif scope_all:
        print(f"全部素材（{len(rows)} 项；含其他会话/历史产物，慎用）")
    elif batch or not batch:
        all_batches = {}
        for r in rows:
            bid = _get_row_batch(r, batch_map)
            if bid:
                if bid not in all_batches:
                    all_batches[bid] = []
                all_batches[bid].append(r)

        if batch == 'all':
            pass
        elif batch == 'latest' or not batch:
            if all_batches:
                latest_bid = max(all_batches.keys(),
                                 key=lambda b: max(r['mtime'] for r in all_batches[b]))
                rows = all_batches[latest_bid]
                print(f"批次过滤: batch={latest_bid}（{len(rows)} 项）")
            else:
                print("批次过滤: 无批次数据（素材可能来自旧版本，无 batch_id 记录）")
        else:
            if batch in all_batches:
                rows = all_batches[batch]
                print(f"批次过滤: batch={batch}（{len(rows)} 项）")
            else:
                print(f"批次 {batch} 不存在。可用批次: {', '.join(all_batches.keys()) or '无'}")
                print("提示: 去掉 --batch 查看全部")
                return 0

    if recent:
        import time as _time
        cutoff = _time.time() - recent * 60
        rows = [r for r in rows if r['mtime'] >= cutoff]

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
    """返回模板 LoadImage 槽位：[(序号, 当前图名, 是否启用), ...]（按节点顺序）。

    未启用槽位 = UI mode 4(bypass) 的占位 LoadImage（引擎跳过、不参与生成），
    由 use --slot N 启用并接线。
    """
    data = json.loads(tpl.read_text(encoding="utf-8-sig"))
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        raise ValueError(f"模板不是 UI 格式: {tpl}")
    slots = []
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "LoadImage":
            vals = n.get("widgets_values") or []
            enabled = int(n.get("mode", 0) or 0) == 0
            slots.append((len(slots), str(vals[0]) if vals else "",
                          enabled, n.get("id")))
    return slots


def _print_slots(tpl: Path) -> None:
    try:
        slots = template_slots(tpl)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return
    print(f"模板 {tpl.name} 参考图槽位（共 {len(slots)} 个，0 起编号）：")
    for idx, cur, enabled, _nid in slots:
        state = "" if enabled else "（禁用，use --slot 启用）"
        print(f"  slot {idx}: {cur or '(空)'} {state}")


def _clone_loadimage(nodes: list, slot: int, defaults: list, y_offset: int = 420) -> dict:
    """克隆一个 LoadImage 节点为禁用占位（mode=4，无接线），返回新节点。"""
    src = next((n for n in nodes if isinstance(n, dict) and n.get("type") == "LoadImage"), None)
    if src is None:
        raise ValueError("模板中没有可克隆的 LoadImage 节点")
    import copy
    new = copy.deepcopy(src)
    max_id = max(int(n.get("id", 0)) for n in nodes)
    new["id"] = max_id + 1
    new["widgets_values"] = [defaults[slot % len(defaults)], "image"]
    pos = new.get("pos") or [0, 0]
    new["pos"] = [pos[0], pos[1] + slot * y_offset]
    new["mode"] = 4  # bypass：占位不参与生成，use --slot N 时自动启用
    for o in new.get("outputs", []):
        o["links"] = []
    nodes.append(new)
    return new


def grow_slots(tpl: Path, total: int, defaults: list = None) -> int:
    """把模板参考槽位扩到 total 个（仅本地镜像模板）。返回现有/新增槽位数。

    目标节点输入采用 COMFY_AUTOGROW_V3（ref_images.* 每行一张），本函数补
    ref_image_{cur..total-1} 行 + 禁用 LoadImage 占位；新增槽位在 use --slot 后生效。
    """
    import copy as _copy  # noqa: F401
    if defaults is None:
        defaults = ["drama_asset_hero.png", "drama_asset_alley.png",
                    "drama_asset_company.png", "drama_asset_father.png",
                    "drama_asset_mother.png", "drama_asset_living.png",
                    "character.png", "scene_00001_.png"]
    data = json.loads(tpl.read_text(encoding="utf-8-sig"))
    nodes = data.get("nodes", [])
    tgt, _rows = _owner_rows(data, "MiniMaxH3ReferenceToVideo", "ref_images.ref_image_")
    if tgt is None:
        raise ValueError(f"{tpl.name} 中没有承载 ref_images.* 的目标节点")
    cur = len(template_slots(tpl))
    added = 0
    for slot in range(cur, total):
        names = {str(i.get("name") or "") for i in tgt.get("inputs", [])}
        if f"ref_images.ref_image_{slot}" not in names:
            tgt.setdefault("inputs", []).append({
                "name": f"ref_images.ref_image_{slot}", "type": "IMAGE",
                "link": None, "widget": None})
        _clone_loadimage(nodes, slot, defaults)
        added += 1
    if added:
        tpl.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return cur + added


def _owner_rows(data: dict, target_type: str, prefix: str) -> tuple:
    """找到承载 ref_images.* 输入的目标节点及其行列表。"""
    for n in data.get("nodes", []):
        if not (isinstance(n, dict) and n.get("type") == target_type):
            continue
        rows = [i for i in (n.get("inputs") or [])
                if str(i.get("name") or "").startswith(prefix)]
        if rows:
            return n, rows
    return None, []


def _wire_slot(data: dict, tgt: dict, row: dict, load_id: int) -> None:
    """把目标节点的 autogrow 输入行接到 LoadImage 输出（生成新 link）。"""
    links = data.get("links", [])
    max_link = max((int(l[0]) for l in links), default=0)
    node = next(n for n in data.get("nodes", [])
                if isinstance(n, dict) and n.get("id") == load_id)
    if row.get("link") is not None:
        return  # 已接线（复用时直接改 widgets 即可）
    slot_idx = next(i for i, x in enumerate(tgt.get("inputs", [])) if x is row)
    new_link = max_link + 1
    links.append([new_link, load_id, 0, tgt.get("id"), slot_idx, "IMAGE"])
    row["link"] = new_link
    for o in node.get("outputs", []):
        if (o.get("name") or "").upper() in ("IMAGE", ""):
            o.setdefault("links", []).append(new_link)
            break


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
    tgt, tgt_rows = _owner_rows(data, "MiniMaxH3ReferenceToVideo", "ref_images.ref_image_")
    patched_nodes = []

    def _apply(n: dict, idx: int) -> None:
        vals = n.get("widgets_values") or []
        if not vals:
            vals = [""]
            n["widgets_values"] = vals
        vals[0] = name
        n["mode"] = 0  # 启用（禁用占位槽位 use 后生效）
        patched_nodes.append((idx, n))

    # 按槽位顺序遍历（与 template_slots 一致），选定目标后启用+接线
    current = 0
    for n in nodes:
        if not (isinstance(n, dict) and n.get("type") == "LoadImage"):
            continue
        hit = False
        if targets.startswith("slot:"):
            hit = current == int(targets.split(":", 1)[1])
        elif targets == "first":
            hit = current == 0
        else:  # all
            hit = True
        if hit:
            _apply(n, current)
        current += 1
        if targets != "all" and hit:
            break

    if not patched_nodes:
        print("[错误] 未能定位要修改的 LoadImage 槽位", file=sys.stderr)
        return 3
    # 为启用槽位接线（autogrow 行 link=None → 生成 link；已接线仅换图）
    if tgt is not None and tgt_rows:
        for idx, n in patched_nodes:
            if idx < len(tgt_rows):
                _wire_slot(data, tgt, tgt_rows[idx], n.get("id"))
    tpl.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已把 {stage} 模板 {tpl.name} 的 LoadImage 指向: {name}（target={targets}，已启用）")
    _print_slots(tpl)
    print("提示：槽位提示词由 prompts/workflows/ 对应文件控制；恢复模板请执行 use --undo。")
    _log(f"use stage={stage} image={name} targets={targets}")
    return 0


def cmd_prune(dirs: dict) -> int:
    """扫描三池，将无效图片（mediacheck 校验失败）移至 quarantine 目录。"""
    from runs.h3 import mediacheck
    rows = _rows(dirs)
    images = [r for r in rows if r["kind"] == "image"]
    quarantined = 0
    for r in images:
        ok, reason = mediacheck.check_image_file(r["full"])
        if ok:
            continue
        src = Path(r["full"])
        day = datetime.now().strftime("%Y%m%d")
        q_dir = ROOT / "uploads" / "_quarantine" / day
        q_dir.mkdir(parents=True, exist_ok=True)
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8] if src.exists() else "unknown"
        dst = q_dir / f"{sha8}_{src.name}"
        counter = 1
        while dst.exists():
            dst = q_dir / f"{sha8}_{src.stem}_{counter}{src.suffix}"
            counter += 1
        try:
            shutil.move(str(src), str(dst))
            quarantined += 1
            print(f"  隔离: {r['name']} ({reason}) -> {dst}")
        except OSError as e:
            print(f"  失败: {r['name']} — {e}", file=sys.stderr)
    print(f"隔离完成：{quarantined}/{len(images)} 张图片移至 uploads/_quarantine/")
    _log(f"prune quarantined={quarantined}/{len(images)}")
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
    p_list.add_argument("--batch", default="", help="按批次过滤: <id>|latest|all")
    p_list.add_argument("--session", default="", help="只显示某会话（cid）上传的素材（book-05 默认隔离；其他历史产物需 --scope-all）")
    p_list.add_argument("--scope-all", action="store_true", help="显示全部素材（含其他会话/历史产物）")
    p_list.add_argument("--recent", type=int, default=0, help="最近 N 分钟内的素材")
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
    p_grow = sub.add_parser("grow")
    p_grow.add_argument("--stage", default="r2v",
                        choices=["i2v", "r2v", "flf2v"])
    p_grow.add_argument("--total", type=int, default=12,
                        help="目标总槽位数（默认 12）")
    sub.add_parser("where")
    sub.add_parser("prune", help="扫描三池，将无效图片隔离至 uploads/_quarantine/")
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
                        name=args.name, limit=args.limit, batch=args.batch,
                        recent=args.recent, session=args.session,
                        scope_all=args.scope_all)
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
    if args.cmd == "grow":
        tpl = _stage_template(args.stage)
        if not tpl.exists():
            print(f"[错误] 该 stage 无本地镜像模板: {tpl}", file=sys.stderr)
            return 3
        if args.total < 1:
            print("[错误] --total 至少为 1", file=sys.stderr)
            return 3
        try:
            now = grow_slots(tpl, args.total)
        except ValueError as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 3
        print(f"已把 {args.stage} 模板扩到 {now} 个参考槽位（新增禁用占位，"
              f"use --slot N 启用）")
        _print_slots(tpl)
        _log(f"grow stage={args.stage} total={now}")
        return 0
    if args.cmd == "where":
        return cmd_where(dirs)
    if args.cmd == "prune":
        return cmd_prune(dirs)
    return 0


def shlex_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(main())
