"""任务监控模块。后台轮询 ComfyUI 任务状态并通过队列推送更新。"""
import time
import os
import queue
import sys
import threading
from pathlib import Path  # 审核修复：poll_batch 曾缺此 import（NameError→恒 failed）
import requests
from typing import Optional

# 监控间隔（秒）
MONITOR_SEC = 15

# ComfyUI 默认地址
COMFYUI_BASE = os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188')


def get_history(prompt_id: str) -> Optional[dict]:
    """查询 ComfyUI 历史任务状态。"""
    try:
        resp = requests.get(f'{COMFYUI_BASE}/history/{prompt_id}', timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def get_queue() -> Optional[dict]:
    """查询 ComfyUI 当前队列。"""
    try:
        resp = requests.get(f'{COMFYUI_BASE}/queue', timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# book-11：状态转移持久化（只在状态/进度变化时落一行，防垃圾）
_PROJECT_ROOT = os.environ.get("VIDEOGEN_PROJECT_ROOT", os.path.expanduser("~/videoGenerate-Model-zju"))
_seen = {}


def _log_tw(event: str) -> None:
    try:
        _runs = os.path.join(_PROJECT_ROOT, "runs")
        if _runs not in sys.path:
            sys.path.insert(0, _runs)
        from h3 import logutil
        logutil.ensure_run_log(_PROJECT_ROOT, "task-watch")
        logutil.log_event("task-watch", event)
    except Exception:  # noqa: BLE001
        pass


def _emit(kind: str, key: str, result: dict) -> dict:
    """状态或进度变化时落一行日志，随后返回 result（原行为不变）。"""
    try:
        sig = (result.get("status"), result.get("progress"))
        k = kind + ":" + key
        if _seen.get(k) != sig:
            _seen[k] = sig
            label = "prompt_id" if kind == "single" else "batch"
            _log_tw(f"poll_state {label}={key} status={sig[0]} progress={sig[1]}")
    except Exception:  # noqa: BLE001
        pass
    return result


def poll_single(prompt_id: str) -> dict:
    """轮询单个任务的当前状态。
    
    Returns:
        {'status': 'queued'|'running'|'completed'|'failed', 'progress': str}
    """
    try:
        # 先查历史
        history = get_history(prompt_id)
        if history and prompt_id in history:
            result = history[prompt_id]
            status_obj = result.get('status', {})
            if status_obj.get('completed', False):
                return _emit('single', prompt_id, {'status': 'completed', 'progress': '✅ 已完成'})
            elif status_obj.get('status_str') == 'error':
                error_msg = result.get('outputs', {}).get('error', '未知错误')
                return _emit('single', prompt_id, {'status': 'failed', 'progress': f'❌ 失败: {error_msg}'})
        
        # 再查队列队
        queue_info = get_queue()
        if queue_info:
            for item in queue_info.get('queue_running', []):
                if len(item) > 1 and item[1] == prompt_id:
                    return _emit('single', prompt_id, {'status': 'running', 'progress': '🔄 生成中...'})
            
            for item in queue_info.get('queue_pending', []):
                if len(item) > 1 and item[1] == prompt_id:
                    return _emit('single', prompt_id, {'status': 'queued', 'progress': '⏳ 排队中...'})
        
        # 未找到任务，可能已失效
        return _emit('single', prompt_id, {'status': 'failed', 'progress': '❌ 任务不存在或已过期'})
        
    except Exception as e:
        return _emit('single', prompt_id, {'status': 'failed', 'progress': f'❌ 查询失败: {str(e)}'})


def poll_batch(manifest_path: str) -> dict:
    """轮询批量任务状态（book-07：读取 manifest.json 的段状态）。"""
    try:
        import json
        m = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        segs = m.get('segments', [])
        total = len(segs)
        done = sum(1 for s in segs if s.get('state') == 'completed')
        failed = sum(1 for s in segs if s.get('state') in ('failed', 'timeout'))
        if failed == 0 and done == total:
            return _emit('batch', manifest_path, {'status': 'completed', 'progress': f'✅ 批量完成 {done}/{total}'})
        if failed and done + failed == total:
            return _emit('batch', manifest_path, {'status': 'failed', 'progress': f'❌ 批量完成 {done}/{total}，失败 {failed}'})
        return _emit('batch', manifest_path, {'status': 'running', 'progress': f'🔄 批量处理中 {done}/{total}'})
    except Exception as e:  # noqa: BLE001
        return {'status': 'failed', 'progress': f'❌ 批量状态读取失败: {e}'}


# book-13 C2：任务首次出现时刻（已耗时用；不持久化，重启即清零）
_first_seen: dict = {}
# 已发过“提交告知/超时提示”的标志（防刷屏）
_notified: set = set()


def _elapsed(prompt_id: str) -> float:
    now = time.monotonic()
    if prompt_id not in _first_seen:
        _first_seen[prompt_id] = now
    return now - _first_seen[prompt_id]


def _eta_hint(status: str) -> str:
    """诚实区间：不给假 ETA，按状态给常规区间与异常提示。"""
    if status == "queued":
        return "排队中（共享服务器，前面可能有人；不会丢）"
    if status == "running":
        return "H3 单段常规 1-20 分钟（360p/5s ≈1-3 分钟；720p/15s ≈10-20 分钟）"
    if status == "failed":
        return "❌ 已失败，请检查日志（可点‘继续’重试）"
    return ""


# ---------------------------------------------------------------------------
# P1 事件驱动完成通知（book-19 §9）：原语——心跳/去重键/四类文案（纯函数，可单测）
# ---------------------------------------------------------------------------
_notify_hb = {"ts": 0.0, "count": 0}


def watcher_beat() -> None:
    """通知 watcher 心跳（每次处理周期调用；供健康校验与降级判定）。"""
    _notify_hb["ts"] = time.monotonic()
    _notify_hb["count"] += 1


def watcher_health(max_age: float = 90.0) -> tuple:
    """心跳新鲜度：(ok, age_seconds)。从未 beat 视为不新鲜（ok=False）。"""
    if not _notify_hb["ts"]:
        return False, -1.0
    age = time.monotonic() - _notify_hb["ts"]
    return age <= max_age, age


def notify_key(cid: str, task_key: str, event: str) -> str:
    """通知去重键：cid+任务标识+事件类目（同任务同类目仅一次）。"""
    return "%s|%s|%s" % (cid, task_key, event)


_p1_notified = set()  # P1：已处理事件键（send 正常走完时 mark；watcher 只接管未处理键）


def p1_mark(cid: str, task_key: str) -> None:
    """send 正常完成监控（完成或失败已展示）时标记：watcher 不再重复注入。"""
    _p1_notified.add(notify_key(cid, task_key, "any"))


def p1_was(cid: str, task_key: str) -> bool:
    """该任务是否已被 send 正常展示过（是→watcher 跳过）。"""
    return notify_key(cid, task_key, "any") in _p1_notified


def build_notify_message(state: str, prompt_id: str = "", detail: str = "",
                         elapsed: float = 0.0) -> str:
    """四类事件文案（book-19 §9）。文案含真实 pid/路径——模型可再查证，
    不得仅凭消息声称产物存在（模型侧校验在 SYSTEM_MESSAGE 既有铁律覆盖）。
    state: completed / failed / queue_timeout / run_timeout / watch_health
    """
    pid = (prompt_id or "")[:8]
    if state == "completed":
        return ("[任务完成] prompt_id=%s 产物=%s。请按真实产物向用户总结（无需再次查询）。"
                % (prompt_id or "?", detail or "见任务日志"))
    if state == "failed":
        return ("[任务失败] prompt_id=%s 原因=%s。请如实向用户汇报失败并询问是否重试。"
                % (prompt_id or "?", detail or "ComfyUI 执行失败"))
    if state == "queue_timeout":
        return ("[任务长时间排队] prompt_id=%s 已排队 %d 分钟仍未开始（共享队列正常现象）。"
                "请告知用户仍在排队，不要重复提交。" % (pid or "?", int(max(0.0, elapsed) // 60)))
    if state == "run_timeout":
        return ("[任务长时间运行] prompt_id=%s 已运行 %d 分钟仍未完成。"
                "请使用查询工具确认真实状态后再汇报。" % (pid or "?", int(max(0.0, elapsed) // 60)))
    return ("[监听异常] 结果通知可能丢失（watcher 心跳过期）。"
            "请使用查询工具确认任务真实状态后再向用户汇报。")


def describe_output(prompt_id: str) -> str:
    """完成事件的产物描述：history->输出文件->远程路径+ffprobe（分辨率/时长）。

    仅描述事实；ffprobe 失败时返回路径本身（不带虚构参数）。远程不可达返回空串。
    """
    try:
        history = get_history(prompt_id)
        entry = (history or {}).get(prompt_id) or {}
        files = []
        for _oid, o in (entry.get("outputs") or {}).items():
            if not isinstance(o, dict):
                continue
            for im in (o.get("images") or []) + (o.get("video") or []):
                if isinstance(im, dict) and im.get("filename"):
                    files.append(im)
        if not files:
            return ""
        files.sort(key=lambda f: 0 if str(f.get("format", "")).lower() in ("mp4", "") else 1)
        f0 = files[0]
        sub = str(f0.get("subfolder") or "").strip("/")
        sub = (sub.strip("/") + "/") if sub else ""
        name = str(f0.get("filename") or "")
        path = sub + name
        remote = "~/ai/ComfyUI/output/" + path
        try:
            import subprocess as _sp
            r = _sp.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-show_entries",
                         "format=duration", "-of", "csv=p=0",
                         os.path.expanduser(remote)],
                        capture_output=True, text=True, timeout=15)
            lines = [ln for ln in (r.stdout or "").splitlines() if ln]
            parts = []
            for ln in lines:
                cols = ln.split(",")
                if len(cols) >= 2 and cols[0].isdigit() and cols[1].isdigit():
                    parts.append("%sx%s" % (cols[0], cols[1]))
                elif cols and cols[0]:
                    try:
                        parts.append("%.2fs" % float(cols[0]))
                    except ValueError:
                        parts.append(cols[0])
            if parts:
                return "%s（%s）" % (remote, ", ".join(parts))
            return remote
        except Exception:  # noqa: BLE001
            return remote
    except Exception:  # noqa: BLE001
        return ""


def _monitor_worker(cid: str, turn_id: int, out_queue: queue.Queue, stop_event: threading.Event):
    """后台监控线程工作函数。
    
    Args:
        cid: 会话 ID
        turn_id: UI 更新令牌
        out_queue: 输出队列，用于向主循环推送消息
        stop_event: 停止信号
    """
    try:
        # 从 session_state 获取任务列表
        try:
            from .session_state import get_tasks, check_turn_valid
        except ImportError:
            from session_state import get_tasks, check_turn_valid
        
        tasks = get_tasks(cid)
        if not tasks:
            out_queue.put({
                'type': 'done',
                'status_html': '',
                'note_md': ''
            })
            return
        
        # 轮询所有任务
        while True:
            # 检查是否应该停止
            if stop_event.is_set() or not check_turn_valid(cid, turn_id):
                break
            
            all_completed = True
            any_failed = False
            status_parts = []
            etas: list = []
            
            results = {}
            for task in tasks:
                if task['type'] == 'single':
                    pid = task['prompt_id']
                    result = poll_single(pid)
                    results[pid] = result
                    el = _elapsed(pid)
                    status_parts.append(f"任务 {pid[:8]}: {result['progress']}（已用 {int(el // 60)} 分 {int(el % 60)} 秒）")
                    etas.append(_eta_hint(result['status']))
                    
                    if result['status'] == 'failed':
                        any_failed = True
                    elif result['status'] != 'completed':
                        all_completed = False
                        
                elif task['type'] == 'batch':
                    result = poll_batch(task['manifest'])
                    status_parts.append(f"批量任务: {result['progress']}")
                    etas.append("逐段进行；段数多时长=段数×单段")
                    
                    if result['status'] == 'failed':
                        any_failed = True
                    elif result['status'] != 'completed':
                        all_completed = False
            
            # 构建状态 HTML
            status_html = '<div class="status-bar monitoring">' + '<br>'.join(status_parts) + '</div>'
            note_md = ' · '.join(e for e in etas if e)[:120] or ' 监控中...'
            # book-13 C2：首次 update 明示后台执行与取片方式（一次即可，防刷屏）
            if not any(k in _notified for k in ('announce',)):
                _notified.add('announce')
                note_md = ('任务已提交，正在后台执行；可随时点「继续」查询进度/取片。' +
                           (' ' + note_md if note_md else ''))
            # 队列/首次加载超 30 分钟提示（观测：H3 首载+排队是 40 分钟事件主因，非卡死）
            if any(_elapsed(t['prompt_id']) > 1800
                   and results.get(t['prompt_id'], {}).get('status') in ('queued', 'running')
                   for t in tasks if t['type'] == 'single') and 'timeout30' not in _notified:
                _notified.add('timeout30')
                note_md = ('⏳ 已超 30 分钟：通常是共享队列等待或 H3 首次加载（正常非卡死）。'
                           '任务仍在后台，可稍后继续查询；不要重复提交。')
            if any(_elapsed(t['prompt_id']) > 1800
                   for t in tasks if t['type'] == 'single') and 'eta' not in _notified and etas:
                _notified.add('eta')
                note_md = note_md + ('；若持续无进展，检查 ComfyUI 队列（dev.py queue）或联系管理员。' if note_md else '')
            
            if any_failed:
                status_html = '<div class="status-bar error">部分任务失败</div>'
                note_md = ' ⚠️ 有任务失败，请检查日志'
                out_queue.put({'type': 'update', 'status_html': status_html, 'note_md': note_md})
                break
            
            if all_completed:
                status_html = '<div class="status-bar success">✅ 所有任务已完成</div>'
                note_md = ' ✅ 本轮完成'
                out_queue.put({'type': 'done', 'status_html': status_html, 'note_md': note_md})
                break
            
            # 推送更新
            out_queue.put({'type': 'update', 'status_html': status_html, 'note_md': note_md})
            
            # 可中断的等待
            stop_event.wait(timeout=MONITOR_SEC)
        
    except Exception as e:
        out_queue.put({
            'type': 'done',
            'status_html': f'<div class="status-bar error">❌ 监控异常: {str(e)}</div>',
            'note_md': f' ⚠️ 监控器异常退出'
        })
