#!/usr/bin/env python3
"""night_runner — 夜间/空闲窗口任务队列（2026-09-07 用户需求：不用每晚手动喊话）。

- **引擎类任务**（kind=engine）：cron 或 --auto 在「夜间窗口 + 队列空闲」时自动执行（如 1080p 探测），
  结果写入状态文件（含产物路径行）。
- **对话类任务**（kind=agent）：需要 agent 协同（口型/插帧/超分叠加等专题），--auto 只提示，
  由用户对助手说"开始夜间任务"，agent 用 run_script("night_runner.py","--list") 查看并逐项认领执行。

用法（spark 仓库根）:
  python3 runs/agent/night_runner.py --list                 # 查看队列（含状态/结果）
  python3 runs/agent/night_runner.py --status               # 摘要（agent 汇报用）
  python3 runs/agent/night_runner.py --add "名称" --exec "cmd" [--kind engine|agent]
  python3 runs/agent/night_runner.py --done <id> [--result "注记"]
  python3 runs/agent/night_runner.py --auto                 # 夜间窗口+队列空闲→顺序执行 engine 类
  python3 runs/agent/night_runner.py --now                  # 等同 --auto 但忽略时间门控（白天测试）

队列：config/night-tasks.json（种子定义）→ 运行状态 config/night-tasks.state.json（gitignore）。
夜间窗口=22:00-次日 08:00（北京时间；spark 为 UTC，脚本内折算）。单实例锁 .night.lock。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE = ROOT / "config" / "night-tasks.json"
STATE = ROOT / "config" / "night-tasks.state.json"
LOCK = ROOT / ".night.lock"
COMFY_URL = "http://127.0.0.1:8188/queue"


def _now_cst() -> tuple:
    """(hour, minute) 北京时间（UTC+8，固定偏移）。"""
    t = time.gmtime(time.time() + 8 * 3600)
    return t.tm_hour, t.tm_min


def is_night_window() -> bool:
    h, _m = _now_cst()
    return h >= 22 or h < 8


def queue_idle() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(COMFY_URL, timeout=8) as r:
            d = json.loads(r.read().decode())
        return not d.get("queue_running") and not d.get("queue_pending")
    except Exception:  # noqa: BLE001
        return False


def load() -> list:
    base = json.loads(QUEUE.read_text(encoding="utf-8"))["tasks"]
    if STATE.exists():
        st = json.loads(STATE.read_text(encoding="utf-8"))
    else:
        st = {}
    return [dict(st.get(t["id"], {}), **{"id": t["id"], "name": t["name"],
                                         "kind": t["kind"], "exec": t.get("exec", ""), "window": t.get("window", "night")})
            if False else {**t, **st.get(t["id"], {})} for t in base]


def save(tasks) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    # 状态文件只存 id→{status, result, claimed_at}
    st = {t["id"]: {k: t[k] for k in ("status", "result", "claimed_at") if k in t}
          for t in tasks}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _status_default(t):
    return t.get("status", "pending")


def cmd_list() -> int:
    for t in load():
        print(f"[{t['id']}] {_status_default(t):10s} {t['kind']:7s} {t['name']}"
              + (f"  | 结果: {str(t.get('result'))[:120]}" if t.get("result") else ""))
    return 0


def cmd_status() -> int:
    tasks = load()
    pend = [t for t in tasks if _status_default(t) == "pending"]
    print(f"待做 {len(pend)} 项 / 共 {len(tasks)} 项；夜间窗口={'ON' if is_night_window() else 'OFF'}；"
          f"队列空闲={'YES' if queue_idle() else 'NO'}")
    for t in pend:
        print(f"  - {t['id']} [{t['kind']}] {t['name']}")
    return 0


def cmd_add(name, exec_, kind) -> int:
    tasks = load()
    tid = "nt-" + time.strftime("%H%M%S", time.gmtime())
    tasks.append({"id": tid, "name": name, "kind": kind or "engine",
                  "exec": exec_ or "", "window": "night"})
    save(tasks)
    print(f"ADDED {tid}")
    return 0


def cmd_done(tid, result) -> int:
    tasks = load()
    hit = next((t for t in tasks if t["id"] == tid), None)
    if not hit:
        print(f"NOT_FOUND {tid}")
        return 1
    hit["status"] = "done"
    if result:
        hit["result"] = result
    save(tasks)
    print(f"DONE {tid}")
    return 0


def _try_lock() -> bool:
    if LOCK.exists():
        return False
    try:
        LOCK.write_text(str(time.time()), encoding="utf-8")
        return True
    except OSError:
        return False


def cmd_auto(now: bool = False) -> int:
    if not _try_lock():
        print("LOCKED: 已有 night_runner 在跑（.night.lock 存在）")
        return 0
    try:
        if not now and not is_night_window():
            print("SKIP: 非夜间窗口（北京时间 22:00-08:00 之外）")
            return 0
        if not queue_idle():
            print("SKIP: ComfyUI 队列未空闲——等下一轮 cron")
            return 0
        tasks = load()
        pend = [t for t in tasks if _status_default(t) == "pending" and t["kind"] == "engine"]
        if not pend:
            agent_pend = [t for t in load() if _status_default(t) == "pending" and t["kind"] == "agent"]
            print("NO_ENGINE_TASKS" + (f"；对话类待做 {len(agent_pend)} 项（请对助手说：开始夜间任务）"
                                       if agent_pend else "；队列已清空"))
            return 0
        for t in pend:
            print(f"=== EXEC {t['id']} {t['name']} ===")
            t["status"] = "claimed"
            t["claimed_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            save(tasks)
            r = subprocess.run(["bash", "-c", t["exec"]], cwd=str(ROOT),
                               capture_output=True, text=True, timeout=14400)
            out = (r.stdout or "") + (r.stderr or "")
            t["status"] = "done" if r.returncode == 0 else "failed"
            t["result"] = (out[-400:] or f"rc={r.returncode}").strip()
            save(tasks)
            print(f"--- {t['id']} {t['status']} rc={r.returncode}")
            print((out[-300:] or ""))
        return 0
    finally:
        try:
            LOCK.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="夜间/空闲窗口任务队列")
    ap.add_argument("--list", action="store_true", help="查看队列")
    ap.add_argument("--status", action="store_true", help="摘要")
    ap.add_argument("--add", action="store_true", help="新增任务（配合 --name/--exec/--kind）")
    ap.add_argument("--name", default="", help="任务名")
    ap.add_argument("--exec", default="", help="bash 执行串（引擎类任务）")
    ap.add_argument("--kind", default="engine", choices=["engine", "agent"])
    ap.add_argument("--done", default="", help="标记完成: <id>")
    ap.add_argument("--result", default="", help="完成注记")
    ap.add_argument("--auto", action="store_true", help="夜间自动执行引擎类")
    ap.add_argument("--now", action="store_true", help="忽略时间门控")
    a = ap.parse_args(argv)
    if a.list:
        return cmd_list()
    if a.status:
        return cmd_status()
    if a.add:
        return cmd_add(a.name, a.exec, a.kind)
    if a.done:
        return cmd_done(a.done, a.result)
    if a.auto or a.now:
        return cmd_auto(now=a.now)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
