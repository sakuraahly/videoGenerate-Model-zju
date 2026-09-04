"""doc_state — 文档状态追踪 + 页面加载预热。

功能：
1. 检测 docs/agent-reading/ 文件变化（sha256 对比）
2. 原子写入 config/doc_state.json（tmp + os.replace）
3. 页面加载时单飞预热（唤醒模型 + 刷新文档描述）

设计：
- 单飞模式：threading.Lock 保证只有一个线程执行预热
- 成功才标记完成；失败允许下次重试
- _prewarm_result 用独立 Lock 保护读写
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)
STATE_FILE = Path(PROJECT_ROOT) / 'config' / 'doc_state.json'

_prewarm_lock = threading.Lock()
_prewarm_result_lock = threading.Lock()
_prewarm_result: dict = {}


def current_hashes() -> dict:
    """计算 docs/agent-reading/ 各文件的 sha256。返回 {filename: sha256}。"""
    from runs.agent.doc_utils import scan_agent_reading_docs
    result = {}
    for filename, _mtime, _size in scan_agent_reading_docs():
        fp = Path(PROJECT_ROOT) / 'docs' / 'agent-reading' / filename
        try:
            data = fp.read_bytes()
            result[filename] = hashlib.sha256(data).hexdigest()[:16]
        except OSError:
            continue
    return result


def check_and_update() -> dict:
    """检查文档变化并原子更新状态文件。返回 diff（空 dict 表示无变化）。"""
    new_hashes = current_hashes()
    old_hashes = {}
    try:
        state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        old_hashes = state.get('hashes', {})
    except (OSError, json.JSONDecodeError):
        pass

    diff = {}
    all_keys = set(new_hashes.keys()) | set(old_hashes.keys())
    for key in all_keys:
        old = old_hashes.get(key)
        new = new_hashes.get(key)
        if old != new:
            diff[key] = {'old': old, 'new': new}

    if diff:
        state = {'hashes': new_hashes, 'updated': _now()}
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(STATE_FILE.parent), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(STATE_FILE))
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    return diff


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def refresh_read_doc_description():
    """刷新 ReadDoc 工具的动态描述（文档列表变化时调用）。"""
    try:
        from runs.agent.doc_utils import scan_agent_reading_docs
        from runs.agent.tools import ReadDoc
        doc_files = [f for f, _, _ in scan_agent_reading_docs()]
        if doc_files:
            base = ReadDoc.description.split('可用文档包括：')[0]
            ReadDoc.description = (
                base + '可用文档包括：' + '、'.join(doc_files)
                + '。用于在任务前了解项目能力与执行协议。'
            )
    except Exception:
        pass


def prewarm():
    """页面加载预热（单飞模式）。

    成功才标记完成；失败允许下次重试。
    不阻塞 UI 线程（由调用方在 daemon 线程中执行）。
    """
    with _prewarm_result_lock:
        if _prewarm_result.get('success'):
            return
    if not _prewarm_lock.acquire(blocking=False):
        return
    try:
        diff = check_and_update()
        if diff:
            refresh_read_doc_description()
        try:
            from runs.agent import llm_mem
            llm_mem.ensure_llm_up(timeout_s=900)
        except Exception as e:
            with _prewarm_result_lock:
                _prewarm_result['success'] = False
                _prewarm_result['error'] = f'模型唤醒失败: {e}'
            return
        with _prewarm_result_lock:
            _prewarm_result['success'] = True
            _prewarm_result['diff'] = diff
    except Exception as e:
        with _prewarm_result_lock:
            _prewarm_result['success'] = False
            _prewarm_result['error'] = str(e)
    finally:
        _prewarm_lock.release()


def get_prewarm_status() -> dict:
    """获取预热状态（线程安全）。"""
    with _prewarm_result_lock:
        return dict(_prewarm_result)
