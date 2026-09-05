"""book-15 L6：服务自愈守护（tmux 会话 agent/sglang）。

用法：
  python runs/agent/supervisor.py once    # 单轮检查（供测试/脚本）
  python runs/agent/supervisor.py watch   # 30s 循环守护（由 tmux 会话 supervisor 承载）

设计：死亡→按启动命令自动拉起（sglang 走 llm_mem.wake 恢复链；agent 走 scheduler 命令）；
单服务连续失败 3 次→写日志报警，不再死循环。所有动作落 logutil（supervisor_* 事件）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_INTERVAL = 30
MAX_ATTEMPTS = 3
def _run(cmd, timeout=30):
    """执行命令并返回 (rc, out, err)；模块级以利单测注入。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") , (r.stderr or "")
    except Exception as e:
        return 1, "", (type(e).__name__ + ": " + str(e))


def _log(text):
    try:
        from h3 import logutil
        logutil.ensure_run_log(PROJECT_ROOT, "supervisor")
        logutil.log_event("supervisor", text)
    except Exception:
        print("[supervisor] " + str(text), flush=True)


def session_alive(name):
    rc, _o, _e = _run(["tmux", "has-session", "-t", name], timeout=10)
    return rc == 0


def port_up(port):
    rc, out, _e = _run(["ss", "-ltn"], timeout=10)
    return bool(out) and ((":" + str(port) + " ") in out)
def relaunch_agent():
    """按文档命令拉起 agent 调度（tmux 会话 agent；venv 激活）。"""
    cmd = ["tmux", "new-session", "-d", "-s", "agent",
           "cd " + str(PROJECT_ROOT) + " && source ~/qwen-agent-venv/bin/activate && "
           "python3 runs/agent/scheduler.py 2>&1 | tee ~/agent.log"]
    rc, _o, _e = _run(cmd, timeout=20)
    return rc == 0


def relaunch_sglang():
    """走 llm_mem.wake 恢复链（含共享内存 planner 前置 /free 与自适应降额）。"""
    try:
        from runs.agent import llm_mem
        return llm_mem.wake(timeout_s=600) == 0
    except Exception as e:
        _log("relaunch_sglang exception: " + type(e).__name__ + ": " + str(e))
        return False


_SERVICES = {
    "agent": {"port": 7860, "relaunch": relaunch_agent},
    "sglang": {"port": 8000, "relaunch": relaunch_sglang},
}
def check_once(strict_port=True):
    """单轮检查；返回 {svc: {ok, alive, port, action}}。"""
    out = {}
    for name, meta in _SERVICES.items():
        alive = session_alive(name)
        up = port_up(meta["port"])
        ok = alive and (up or not strict_port)
        out[name] = {"ok": ok, "alive": alive, "port": up, "action": ""}
    return out


def ensure(attempts):
    """对不 OK 服务拉起（上限 MAX_ATTEMPTS）；attempts={svc: count} 调用方持久防死循环。"""
    results = check_once()
    for name, st in results.items():
        if st["ok"]:
            attempts[name] = 0
            continue
        attempts[name] = attempts.get(name, 0) + 1
        if attempts[name] > MAX_ATTEMPTS:
            _log(name + " 连续 " + str(attempts[name] - 1) + " 次拉起失败，暂停并等待人工")
            st["action"] = "alarm"
            continue
        _log("不健康 " + name + " alive=" + str(st["alive"]) + " port=" + str(st["port"]) + " → 拉起")
        ok = _SERVICES[name]["relaunch"]()
        if ok:
            st["action"] = "relaunched"
            attempts[name] = 0
        else:
            st["action"] = "failed"
            _log("拉起失败 " + name)
    return results
def main(argv=None):
    ap = argparse.ArgumentParser(description="book-15 L6 服务自愈守护")
    ap.add_argument("cmd", choices=["once", "watch"], default="once")
    ap.add_argument("--interval", type=int, default=LOG_INTERVAL)
    args = ap.parse_args(argv)
    attempts = {}
    if args.cmd == "once":
        res = ensure(attempts)
        for name, st in res.items():
            print(name, "ok=" + str(st["ok"]), "action=" + str(st["action"]))
        return 0
    _log("supervisor watch 启动（interval=" + str(args.interval) + "s）")
    while True:
        try:
            ensure(attempts)
        except Exception as e:
            _log("watch loop error: " + type(e).__name__ + ": " + str(e))
        time.sleep(max(10, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
