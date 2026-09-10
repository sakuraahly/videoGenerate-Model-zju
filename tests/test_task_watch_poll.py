#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_task_watch_poll.py — 任务轮询抗误报单测（2026-09-10 长任务误报失败修复）。

实测事故：18s r2v 大任务在跑时，watcher 因 /queue 瞬时超时/查不到，
把任务判成"不存在或已过期"，并向 agent/用户注入失败消息（failed↔running 抖动）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.agent import task_watch as tw  # noqa: E402


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL:', msg)
        else:
            print('ok:', msg)

    orig_h, orig_q = tw.get_history, tw.get_queue
    try:
        pid = 'aaaa-bbbb'

        # 1) 队列查询失败（None）→ 不能判失败
        tw.get_history = lambda p: None
        tw.get_queue = lambda: None
        r = tw.poll_single(pid)
        check(r['status'] == 'running', '队列查询失败 → 仍视为运行中（不误报失败）')

        # 2) 查询抛异常 → 仍视为运行中
        def _boom():
            raise RuntimeError('timeout')
        tw.get_queue = _boom
        r = tw.poll_single(pid)
        check(r['status'] == 'running', '查询异常 → 仍视为运行中')

        # 3) 连续 2 次未找到 → 仍 running（宽限）；第 3 次才 failed
        tw.get_queue = lambda: {'queue_running': [], 'queue_pending': []}
        tw._miss_counts.pop(pid, None)
        r1 = tw.poll_single(pid)
        r2 = tw.poll_single(pid)
        r3 = tw.poll_single(pid)
        check(r1['status'] == 'running' and r2['status'] == 'running',
              '连续 1-2 次查不到 → 状态确认中（不误报）')
        check(r3['status'] == 'failed', '连续 3 次查不到 → 判失效')

        # 4) 在队列里 running → running，且清空未找到计数
        tw._miss_counts[pid] = 2
        tw.get_queue = lambda: {'queue_running': [[1, pid, {}]], 'queue_pending': []}
        r = tw.poll_single(pid)
        check(r['status'] == 'running' and pid not in tw._miss_counts,
              '队列命中 → 运行中并清零计数')

        # 5) 历史已完成 → completed
        tw.get_history = lambda p: {p: {'status': {'completed': True, 'status_str': 'success'},
                                        'outputs': {}}}
        r = tw.poll_single(pid)
        check(r['status'] == 'completed', '历史已完成 → completed')

        # 6) 历史明确 error → failed
        tw.get_history = lambda p: {p: {'status': {'completed': False, 'status_str': 'error'},
                                        'outputs': {'error': 'boom'}}}
        r = tw.poll_single(pid)
        check(r['status'] == 'failed', '历史明确 error → failed')
    finally:
        tw.get_history, tw.get_queue = orig_h, orig_q
        tw._miss_counts.clear()

    print('ALL_OK' if ok else 'SOME_FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
