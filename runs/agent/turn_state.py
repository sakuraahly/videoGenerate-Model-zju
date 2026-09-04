"""turn_state — 回合级共享状态（重试计数 + 熔断器）。

设计：单用户单会话（当前 UI 不支持多用户并发）。
- 不可恢复失败（exit 3 / ⛔）：独立计数，上限 3 次后熔断
- 可恢复失败（exit 2 / 超时）：独立计数，上限 5 次后熔断
- 成功时重置该 key 的所有计数
- 新素材上传后重置所有计数（换素材 = 换问题根因）
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_retry_counts: dict[str, int] = {}
_recoverable_counts: dict[str, int] = {}
_active_batch: str | None = None

MAX_DETERMINISTIC_RETRIES = 3
MAX_RECOVERABLE_RETRIES = 5


def begin_turn(batch_id: str | None = None):
    global _active_batch
    with _lock:
        _active_batch = batch_id


def bump_retry(key: str, recoverable: bool = False) -> int:
    """递增计数并返回当前值。recoverable=True 走独立计数器。"""
    with _lock:
        if recoverable:
            _recoverable_counts[key] = _recoverable_counts.get(key, 0) + 1
            return _recoverable_counts[key]
        else:
            _retry_counts[key] = _retry_counts.get(key, 0) + 1
            return _retry_counts[key]


def reset_retry(key: str):
    """成功时重置该 key 的所有计数。"""
    with _lock:
        _retry_counts.pop(key, None)
        _recoverable_counts.pop(key, None)


def reset_deterministic_only(key: str):
    """可恢复失败时仅重置不可恢复计数（保留可恢复计数）。"""
    with _lock:
        _retry_counts.pop(key, None)


def get_active_batch() -> str | None:
    with _lock:
        return _active_batch


def reset_all_on_upload():
    """新素材上传后重置所有计数（换素材 = 换问题根因）。"""
    with _lock:
        _retry_counts.clear()
        _recoverable_counts.clear()
