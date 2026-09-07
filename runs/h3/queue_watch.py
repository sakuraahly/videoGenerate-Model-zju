#!/usr/bin/env python3
"""queue_watch — ComfyUI 队列空闲监听 + 复检（book-19 S7 二级验证/共享队列纪律工具）。

背景：共享队列（用户任务 + 项目任务）——加入长任务前必须先确认队列真的空闲：
本脚本轮询 /queue，首次探测到 running+pending 均为空后**强制复检**
（连续 --confirm 次探测间隔 --confirm-wait 秒仍为空），全过才输出
QUEUE_IDLE_CONFIRMED（exit 0）；复检期间任何任务进场都会重置复检计数。

失败安全：队列接口不可达视为"忙"（不确认、重置复检），绝不误判空闲。

用法：
  python runs/h3/queue_watch.py once                      # 单次快照（不等待）
  python runs/h3/queue_watch.py idle [--confirm N]        # 等待空闲（默认复检 2 次）
        [--confirm-wait 10] [--interval 10] [--timeout 1800] [--comfyui-url ...]
退出码：0=已确认空闲（QUEUE_IDLE_CONFIRMED 行）；2=超时（QUEUE_BUSY_TIMEOUT）；
       3=参数错误/初始化失败。

队列纪律（book-19 §5）：确认空闲后仍建议 --submit-only 提交（任务进排队、不阻塞），
运行结果由 h3_submit.py（无参重跑/--resume 轮询续传）或 task_watch 监听收取。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
    sys.path.insert(0, os.path.join(_REPO, "runs"))

EXIT_CONFIRMED = 0
EXIT_TIMEOUT = 2
EXIT_INIT = 3


def make_client(comfyui_url: str = ""):
    """构造 ComfyClient（默认 COMFYUI_URL/127.0.0.1:8188；低重试适合轮询）。"""
    from h3 import comfy

    return comfy.ComfyClient(
        base_url=comfyui_url or None,
        retries=1,
        base_delay=1.0,
        request_timeout=5,
    )


def probe(client) -> str:
    """单次探测：返回 'idle' | 'busy' | 'unreachable'（不可达视为忙）。"""
    try:
        running, pending = client.queue_pids()
        if running or pending:
            return "busy"
        return "idle"
    except Exception:  # noqa: BLE001
        return "unreachable"


def wait_idle(client, confirm: int = 2, confirm_wait: float = 10.0,
              interval: float = 10.0, timeout: float = 1800.0,
              log=print) -> bool:
    """等待队列空闲并复检确认。

    状态机：streak=连续 'idle' 探测次数；busy/unreachable 重置为 0；
    streak >= confirm → 返回 True（已确认）。timeout 秒后返回 False。
    """
    confirm = max(1, int(confirm))
    interval = max(1.0, float(interval))
    confirm_wait = max(1.0, float(confirm_wait))
    timeout = max(1.0, float(timeout))
    t0 = time.monotonic()
    streak = 0
    while True:
        state = probe(client)
        if state == "idle":
            streak += 1
        else:
            streak = 0
        log(f"[queue_watch] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"queue={state} streak={streak}/{confirm}")
        if streak >= confirm:
            return True
        if time.monotonic() - t0 >= timeout:
            return False
        time.sleep(interval if state != "idle" else confirm_wait)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ComfyUI 队列空闲监听+复检")
    ap.add_argument("mode", choices=["once", "idle"])
    ap.add_argument("--confirm", type=int, default=2,
                    help="空闲确认所需连续探测次数（默认 2=首次空闲后复检 1 次）")
    ap.add_argument("--confirm-wait", type=float, default=10.0,
                    help="复检间隔秒（空闲状态下的探测间隔）")
    ap.add_argument("--interval", type=float, default=10.0,
                    help="忙状态探测间隔秒")
    ap.add_argument("--timeout", type=float, default=1800.0,
                    help="总超时秒（超时=QUEUE_BUSY_TIMEOUT exit 2）")
    ap.add_argument("--comfyui-url", type=str, default="",
                    help="ComfyUI 地址（默认 COMFYUI_URL 或 127.0.0.1:8188）")
    args = ap.parse_args(argv)
    client = make_client(args.comfyui_url)

    if args.mode == "once":
        state = probe(client)
        print(f"QUEUE_STATE={state}")
        return 0 if state == "idle" else 2

    ok = wait_idle(client, confirm=args.confirm, confirm_wait=args.confirm_wait,
                   interval=args.interval, timeout=args.timeout)
    if ok:
        print("QUEUE_IDLE_CONFIRMED")
        return EXIT_CONFIRMED
    print("QUEUE_BUSY_TIMEOUT")
    return EXIT_TIMEOUT


if __name__ == "__main__":
    sys.exit(main())
