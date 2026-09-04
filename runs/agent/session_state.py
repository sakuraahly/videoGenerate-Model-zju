"""会话状态管理模块。存储所有跨文件共享的会话级状态。"""
import threading

# 每个会话的任务列表: cid → [{'prompt_id': str, 'type': 'single'} | {'manifest': str, 'type': 'batch'}]
_session_tasks = {}

# UI 更新令牌: cid → int (每次新 turn 递增)
_session_turn_ids = {}

# 停止信号: cid → threading.Event
_stop_events = {}

# 全局锁，保护上述字典的并发访问
_state_lock = threading.Lock()


def get_turn_id(cid: str) -> int:
    """获取当前会话的 turn ID（用于 UI 更新验证）。"""
    with _state_lock:
        return _session_turn_ids.get(cid, 0)


def check_turn_valid(cid: str, turn_id: int) -> bool:
    """检查给定的 turn_id 是否仍是当前会话的最新值。"""
    with _state_lock:
        return _session_turn_ids.get(cid, -1) == turn_id


def get_stop_event(cid: str) -> threading.Event:
    """获取或创建会话级别的停止事件。"""
    with _state_lock:
        if cid not in _stop_events:
            _stop_events[cid] = threading.Event()
        return _stop_events[cid]


def clear_tasks(cid: str):
    """清空指定会话的所有任务记录（新 turn 开始时调用）。"""
    with _state_lock:
        _session_tasks[cid] = []


def add_tasks(cid: str, tasks: list):
    """向指定会话追加任务记录（支持多轮 auto-continue 累积）。"""
    with _state_lock:
        if cid not in _session_tasks:
            _session_tasks[cid] = []
        _session_tasks[cid].extend(tasks)


def get_tasks(cid: str) -> list:
    """获取指定会话的所有任务记录。"""
    with _state_lock:
        return list(_session_tasks.get(cid, []))


def increment_turn_id(cid: str) -> int:
    """递增并返回新的 turn ID（新 turn 开始时调用）。"""
    with _state_lock:
        current = _session_turn_ids.get(cid, 0) + 1
        _session_turn_ids[cid] = current
        return current
