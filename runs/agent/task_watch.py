"""任务监控模块。后台轮询 ComfyUI 任务状态并通过队列推送更新。"""
import time
import os
import queue
import sys
import threading
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
            
            for task in tasks:
                if task['type'] == 'single':
                    result = poll_single(task['prompt_id'])
                    status_parts.append(f"任务 {task['prompt_id'][:8]}: {result['progress']}")
                    
                    if result['status'] == 'failed':
                        any_failed = True
                    elif result['status'] != 'completed':
                        all_completed = False
                        
                elif task['type'] == 'batch':
                    result = poll_batch(task['manifest'])
                    status_parts.append(f"批量任务: {result['progress']}")
                    
                    if result['status'] == 'failed':
                        any_failed = True
                    elif result['status'] != 'completed':
                        all_completed = False
            
            # 构建状态 HTML
            status_html = '<div class="status-bar monitoring">' + '<br>'.join(status_parts) + '</div>'
            note_md = ' 监控中...'
            
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
