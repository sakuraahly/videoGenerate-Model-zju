#!/usr/bin/env python3
"""会话产物目录协议（planbook §15d 产物可达性）：logs/agent_chats/<cid>/outputs/。

协议（三处同口径，改动必四方核对——ui_app / lipsync_chain / 本文档单元测试）：
  1) 链/引擎最终产物 → place_output() 复制到「当前会话」产物目录；
     会话 id 来自 env `VIDEOGEN_SESSION_CID`（run_script 由 CURRENT_SESSION 注入）。
  2) UI（runs/agent/ui_app.py 结果区）→ session_videos()/session_files() 读取展示
     （gr.Video 预览最新 + gr.File 全部下载）。
  3) 保留策略：每会话最多 KEEP（默认 10）个文件，更旧的自动修剪删除。

路径口径（spark 与 Windows 主库一致）：<repo>/logs/agent_chats/<cid>/outputs/。

反查兜底（2026-09-11 用户要求：生成好的任务必须自动回传到 UI 界面）：
  产物没进会话目录时（后台 --submit-only 完成、watcher 接管、服务重启后会话上下文丢失），
  用会话档（<cid>.jsonl）里的 prompt_id 去 workflows/*/job.json 反查任务 → 取该任务的
  本机产物。纯读接口 latest_final()；UI 刷新前调 adopt_outputs() 把反查到的成品**回写**
  会话目录并打标（Gradio 只服务 allowed_paths 内的文件，可直接回传）。
  详见文件尾「反查兜底」一节。
"""
from __future__ import annotations

import os
import shutil
import time as _tm
from pathlib import Path

ENV_CID = 'VIDEOGEN_SESSION_CID'
KEEP = 10
# 「成品」标记（2026-09-10 用户要求：UI 回传/下载的必须是成品，不是队列原始产物）：
# 会话产物目录里同时会落入"队列直出"和"成品（配音/字幕/后期后的终版）"两类文件，
# 过去结果区取的是"最新 mtime"，容易被二次后期或补跑的文件顶掉。现在成品显式打标，
# UI 优先预览/下载它。
FINAL_MARKER = '_final.json'
VIDEO_EXTS = ('.mp4', '.webm', '.mov', '.mkv', '.gif')


def current_cid() -> str:
    """链侧读取：run_script 注入的 VIDEOGEN_SESSION_CID（无则空串=不落会话目录）。"""
    return (os.environ.get(ENV_CID, '') or '').strip()


def session_out_dir(repo: Path, cid: str) -> Path | None:
    """会话产物目录；cid 为空返回 None（无会话上下文不落盘）。"""
    cid = str(cid or '').strip()
    if not cid:
        return None
    return Path(repo) / 'logs' / 'agent_chats' / cid / 'outputs'


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _list_dir(repo: Path, cid: str, exts: tuple | None) -> list:
    d = session_out_dir(repo, cid)
    if d is None or not d.is_dir():
        return []
    try:
        items = [p for p in d.iterdir() if p.is_file()
                 and (exts is None or p.suffix.lower() in exts)]
    except OSError:
        return []
    items.sort(key=_mtime, reverse=True)
    return items


def _dedup_head(f: Path, items: list) -> list:
    """把 f 提到列表最前并去重（Path 等值比较；用于「成品排第一」）。"""
    return [Path(f)] + [p for p in items if Path(p) != Path(f)]


def session_files(repo: Path, cid: str) -> list:
    """会话全部产物文件，最新在前（供 gr.File 下载列表）。

    反查兜底命中的成品可能不在会话目录里（回写失败时），也一并列出——否则
    「查得到却下载不了」。去重交给调用方（ui_app 会按 resolve 去重）。
    """
    # 内部标记文件（_final.json）不是产物，不放进给用户的下载列表
    files = [p for p in _list_dir(repo, cid, None) if p.name != FINAL_MARKER]
    f = latest_final(repo, cid)
    if f is None or not Path(f).is_file():
        return files
    return _dedup_head(Path(f), files)


def mark_final(repo: Path, cid: str, path) -> bool:
    """把某个产物标记为「成品」（写 _final.json）——UI 优先预览/下载它。"""
    d = session_out_dir(repo, cid)
    if d is None:
        return False
    try:
        import json as _json
        d.mkdir(parents=True, exist_ok=True)
        (d / FINAL_MARKER).write_text(
            _json.dumps({'name': Path(path).name, 'ts': _tm.time()}, ensure_ascii=False),
            encoding='utf-8')
        return True
    except OSError:
        return False


def _latest_final_local(repo: Path, cid: str):
    """只在**会话产物目录内**找成品：_final.json 标记 → 命名兜底（*_final/_pp/_mix/tts）。"""
    d = session_out_dir(repo, cid)
    if d is None or not d.is_dir():
        return None
    try:
        import json as _json
        m = d / FINAL_MARKER
        if m.is_file():
            name = str((_json.loads(m.read_text(encoding='utf-8')) or {}).get('name') or '')
            p = d / name
            if name and p.is_file():
                return p
    except Exception:  # noqa: BLE001
        pass
    # 命名兜底只看**媒体文件**（否则会把 _final.json 标记自己当成成品；单测抓到过）
    for p in _list_dir(repo, cid, VIDEO_EXTS):
        stem = p.stem.lower()
        if any(k in stem for k in ('_final', '_pp', '_mix', 'tts')):
            return p
    return None


def latest_final(repo: Path, cid: str):
    """最近一次标记的成品文件；会话目录没有时依次退化：命名兜底 → 反查兜底 → None。

    反查命中的路径可能不在会话目录里（原样返回，供预览/下载）；需要落到
    Gradio 可服务目录时用 adopt_outputs()。
    """
    p = _latest_final_local(repo, cid)
    if p is not None:
        return p
    return _final_by_reverse(repo, cid)


def session_videos(repo: Path, cid: str) -> list:
    """会话产物视频，**成品在前**，其后按 mtime 倒序（供 gr.Video 预览 / 跳过非媒体文件）。

    成品来自反查兜底时不在会话目录里 → 仍需排第一并返回（原实现用 `f in vids`
    判定，会把反查结果整个丢掉 → 结果区恒「暂无结果」，即 2026-09-11 的回传断链）。
    """
    vids = _list_dir(repo, cid, VIDEO_EXTS)
    f = latest_final(repo, cid)
    if f is None or not Path(f).is_file() or Path(f).suffix.lower() not in VIDEO_EXTS:
        return vids
    return _dedup_head(Path(f), vids)


def prune_dir(d: Path, keep: int = KEEP) -> None:
    """修剪：保留最新 keep 个文件（按 mtime），更旧的删除。"""
    try:
        items = [p for p in d.iterdir() if p.is_file()]
        items.sort(key=_mtime, reverse=True)
        for p in items[keep:]:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def place_output(repo: Path, cid: str, src: Path,
                 name: str | None = None, keep: int = KEEP, final: bool = False) -> Path | None:
    """把最终产物复制到会话产物目录（mtime 刷新为当前，修剪旧文件）。

    失败（无会话上下文/IO 异常）返回 None，调用方按警告处理、不得中断主流程。
    """
    d = session_out_dir(repo, cid)
    if d is None:
        return None
    try:
        d.mkdir(parents=True, exist_ok=True)
        dst = d / (name or Path(src).name)
        shutil.copy2(str(src), str(dst))
        os.utime(dst, (_tm.time(), _tm.time()))
        if final:
            mark_final(repo, cid, dst)
        prune_dir(d, keep)
        return dst
    except OSError:
        return None


# ---------------------------------------------------------------------------
# 反查兜底（2026-09-11 用户要求：生成好的任务必须自动回传到 UI 界面）
# ---------------------------------------------------------------------------
# 触发场景（会话产物目录为空或没有成品标记）：
#   * 任务走 --submit-only 在后台完成，落盘进程没有 VIDEOGEN_SESSION_CID（env 丢失）；
#   * watcher/服务重启后接管，会话级任务表在内存里已丢；
#   * 产物只落在 <repo>/outputs/，没人再执行 place_output。
# 做法：会话档 <cid>.jsonl 里出现过 prompt_id（模型汇报/工具输出都会复述）→
#   在 workflows/*/job.json 里反查命中该任务 → 取该任务的**本机产物**。
# 产物来源（按可靠性排序）：
#   a) job.json.output_file（任务完成时 h3_submit 写入，ComfyUI 侧文件名）→ outputs/<name>
#   b) 该任务自己的运行日志的 LOCAL_OUTPUT 行（h3_submit 直跑落盘处）
#   c) 提到该 prompt_id 的运行日志的 LOCAL_OUTPUT 行（job.json 缺 log_file 的老任务）
#   d) 任务目录里的 mp4（最老的形态）
# 铁律：
#   * job.json.videos/audios 是**输入**参考素材（resume 恢复用，见 h3_submit
#     record_task_start / --resume 的 _jv 分支），绝不可当成成品回传——
#     否则会把用户上传的素材当成"生成的视频"展示；
#   * 跨任务扫日志必须先用 prompt_id 过滤：LOCAL_OUTPUT 行不带任务号，
#     不过滤会把别人的产物当成本会话成品。
# ---------------------------------------------------------------------------
_RUN_LOG_PATTERNS = ('run_*.log', 'run_*.log.1')   # .1 = logutil 5MB 旋转档
_LOG_SCAN_LIMIT = 60                               # 反查日志上限（按 mtime 最新优先）
_MEDIA_EXTS = VIDEO_EXTS + ('.png', '.jpg', '.jpeg', '.webp')
_REVERSE_TTL = 5.0                                 # 反查结果记忆（UI 定时刷新用）
_reverse_cache: dict = {}


def _session_prompt_ids(repo: Path, cid: str) -> list:
    """从会话 jsonl 里抽出出现过的任务号（UUID，按出现顺序去重=由旧到新）。"""
    import json as _json, re as _re
    out: list = []
    try:
        f = Path(repo) / 'logs' / 'agent_chats' / ('%s.jsonl' % cid)
        if not f.is_file():
            return out
        txt = f.read_text(encoding='utf-8', errors='replace')
        for m in _re.findall(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
                             txt, _re.IGNORECASE):
            if m not in out:
                out.append(m)
    except Exception:  # noqa: BLE001
        pass
    return out


def _task_log_paths(repo: Path, task_dir: Path, job: dict) -> list:
    """任务运行日志候选路径。

    job.json.log_file 存的是 **basename**：h3_submit.record_task_start 写
    `os.path.basename(run_log)`，_adopt_task_log 也从 `<repo>/logs/<name>` 取回。
    原实现用 `task_dir / log_name` 拼接 → 该文件从不存在 → 任务日志里的
    LOCAL_OUTPUT 永远读不到（2026-09-11 反查返回 None 的直接原因）。
    """
    name = Path(str((job or {}).get('log_file') or '')).name
    if not name:
        return []
    return [Path(repo) / 'logs' / name,
            Path(repo) / 'logs' / (name + '.1'),   # 旋转档
            Path(task_dir) / name]                 # 历史形态：日志曾与任务同目录


def _outputs_from_log(repo: Path, log_path) -> list:
    """运行日志里的 LOCAL_OUTPUT 行 → 本机产物路径（相对路径按项目根解析）。

    用「整行取值」而不是非空白分词：产物名可能含空格/中文（用户提示词命名）。
    """
    import re as _re
    out: list = []
    try:
        text = Path(log_path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return out
    for m in _re.finditer(r'LOCAL_OUTPUT:\s*(.+?)\s*$', text, _re.MULTILINE):
        raw = m.group(1).strip().strip('"').strip("'")
        if not raw:
            continue
        p = Path(raw)
        if p.suffix.lower() not in _MEDIA_EXTS:
            continue
        out.append(p if p.is_absolute() else Path(repo) / p)
    return out


def _newest_existing(cands: list):
    """候选中挑真实存在且 mtime 最新的一个（同任务多产物=取最后落盘的终版）。"""
    best, best_t = None, -1.0
    for c in cands:
        c = Path(c)
        try:
            if not c.is_file():
                continue
        except OSError:
            continue
        t = _mtime(c)
        if t > best_t:
            best, best_t = c, t
    return best


def _product_of_task(repo: Path, task_dir: Path):
    """取某任务的成品路径（本机文件；找不到返回 None）。只认输出，不认输入素材。"""
    import json as _json
    job: dict = {}
    try:
        job = _json.loads((task_dir / 'job.json').read_text(encoding='utf-8-sig')) or {}
    except Exception:  # noqa: BLE001
        job = {}
    cands: list = []
    # a) 完成时写入的 output_file（ComfyUI 侧文件名，本机副本在 outputs/）
    name = Path(str(job.get('output_file') or '')).name
    if name:
        cands.append(Path(repo) / 'outputs' / name)
    # b) 任务自己的日志
    for lf in _task_log_paths(repo, task_dir, job):
        cands.extend(_outputs_from_log(repo, lf))
    got = _newest_existing(cands)
    if got is not None:
        return got
    # c) 最老形态兜底：任务目录里的 mp4
    try:
        vids = sorted(task_dir.glob('*.mp4'), key=_mtime, reverse=True)
    except OSError:
        vids = []
    return vids[0] if vids else None


def _job_files_for(repo: Path, prompt_id: str) -> list:
    """workflows/*/job.json 中包含该任务号的（目录名自带时间戳 → 名字倒序≈新任务优先）。"""
    out: list = []
    try:
        files = sorted(Path(repo).glob('workflows/*/job.json'), reverse=True)
    except OSError:
        return out
    for jf in files:
        try:
            txt = jf.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if prompt_id in txt:
            out.append(jf)
    return out


def _logs_for_prompt(repo: Path, prompt_id: str) -> list:
    """提到该 prompt_id 的运行日志，最新优先（限量；先读最新的一批）。"""
    pid = str(prompt_id or '').strip().lower()
    if not pid:
        return []
    logs: list = []
    for pat in _RUN_LOG_PATTERNS:
        try:
            logs.extend((Path(repo) / 'logs').glob(pat))
        except OSError:
            pass
    logs.sort(key=_mtime, reverse=True)
    out: list = []
    for lf in logs[:_LOG_SCAN_LIMIT]:
        try:
            if pid in lf.read_text(encoding='utf-8', errors='replace').lower():
                out.append(lf)
        except OSError:
            continue
    return out


def _reverse_scan(repo: Path, cid: str):
    """真正的反查：会话档 prompt_id（新→旧）→ 任务 job.json / 任务日志 → 成品文件。"""
    for pid in reversed(_session_prompt_ids(repo, cid)):
        for jobf in _job_files_for(repo, pid):
            got = _product_of_task(repo, jobf.parent)
            if got is not None:
                return got
        # job.json 缺失/无 output_file/log_file 的老任务：靠本任务日志里的 LOCAL_OUTPUT
        for lf in _logs_for_prompt(repo, pid):
            got = _newest_existing(_outputs_from_log(repo, lf))
            if got is not None:
                return got
    return None


def _final_by_reverse(repo: Path, cid: str):
    """反查兜底（带 TTL 记忆：UI 结果区定时刷新会反复调用）。"""
    key = (str(repo), str(cid))
    now = _tm.monotonic()
    hit = _reverse_cache.get(key)
    if hit is not None and now - hit[0] < _REVERSE_TTL:
        cached = hit[1]
        if not cached:
            return None
        p = Path(cached)
        if p.is_file():
            return p
    found = _reverse_scan(repo, cid)
    _reverse_cache[key] = (now, str(found) if found else '')
    return found


def adopt_outputs(repo: Path, cid: str):
    """反查兜底 + **回写会话目录**：UI 结果区刷新前调用（幂等；失败返回 None 不影响展示）。

    为什么必须回写：Gradio 只服务 allowed_paths 内的文件（ui_app 放行的是会话产物目录），
    产物若只躺在 <repo>/outputs/，页面上会「查得到、放不出来」。复制回会话目录并打标后
    预览/下载都正常，且下次刷新直接走最快路径（不再反查）。
    """
    if session_out_dir(repo, cid) is None:
        return None
    local = _latest_final_local(repo, cid)
    if local is not None:
        return local
    src = _final_by_reverse(repo, cid)
    if src is None:
        return None
    try:
        placed = place_output(Path(repo), str(cid), Path(src), final=True)
    except Exception:  # noqa: BLE001
        placed = None
    return placed or src
