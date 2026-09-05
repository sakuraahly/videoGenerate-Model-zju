"""book-15 L7：服务编排观测与动作（spark 侧入口；dev.py services 调用）。

用法：python3 runs/agent/svc_main.py status | restart-llm | restart-agent | selfcheck
全部动作走项目程序（llm_mem/queue_probe）；ComfyUI 一律不重启。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))  # 直跑时也可 import runs.agent.*
if str(PROJECT_ROOT / 'runs') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'runs'))


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 1, "", (type(e).__name__ + ": " + str(e))


def port_up(port):
    rc, out, _ = _run(["ss", "-ltn"])
    return bool(out) and ((":" + str(port) + " ") in out)


def session_alive(name):
    rc, _o, _e = _run(["tmux", "has-session", "-t", name])
    return rc == 0


def systemd_enabled(name):
    rc, _o, _e = _run(["systemctl", "is-enabled", name])
    return rc == 0
def collect_status():
    """只读汇总：三服务 端口/会话/自启 + LLM 档位 + 最近 planner 事件。"""
    out = {"services": {}, "llm": {}, "planner_events": []}
    out["services"]["comfyui"] = {
        "port": port_up(8188),
        "systemd_enabled": systemd_enabled("comfyui.service"),
    }
    out["services"]["sglang"] = {"port": port_up(8000), "session": session_alive("sglang")}
    out["services"]["agent"] = {"port": port_up(7860), "session": session_alive("agent")}
    out["services"]["supervisor"] = {"session": session_alive("supervisor")}
    try:
        from runs.agent import llm_mem
        cfg = llm_mem.load_cfg()
        out["llm"] = {"mem_fraction": cfg.get("mem_fraction"),
                      "max_running_requests": cfg.get("max_running_requests"),
                      "context_length": cfg.get("context_length"),
                      "speculative": cfg.get("speculative", True)}
    except Exception as e:
        out["llm"] = {"error": type(e).__name__ + ": " + str(e)[:120]}
    try:
        import glob
        logs = sorted(glob.glob(str(PROJECT_ROOT / "logs" / "run_*.log")),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for f in logs[:3]:
            lines = [l for l in open(f, encoding="utf-8", errors="replace")
                     if "planner_" in l or "llm-mem" in l]
            out["planner_events"] += lines[-3:]
    except Exception:
        pass
    return out


def cmd_status():
    print(json.dumps(collect_status(), ensure_ascii=False, indent=1))
    return 0


def cmd_restart_llm():
    """安全恢复链：队列空闲检查→/free→wake(自适应)。"""
    try:
        from runs.agent import llm_mem
        if not llm_mem.comfy_queue_idle():
            print(json.dumps({"ok": False, "msg": "ComfyUI 队列非空闲，已中止（共享服务器纪律）"}))
            return 2
        llm_mem.planner_prep()
        rc = llm_mem.wake(timeout_s=600)
        print(json.dumps({"ok": rc == 0, "msg": "wake rc=" + str(rc)}))
        return 0 if rc == 0 else 1
    except Exception as e:
        print(json.dumps({"ok": False, "msg": type(e).__name__ + ": " + str(e)[:160]}))
        return 1


def cmd_restart_agent():
    _run(["tmux", "kill-session", "-t", "agent"])
    cmd = ["tmux", "new-session", "-d", "-s", "agent",
           "cd " + str(PROJECT_ROOT) + " && source ~/qwen-agent-venv/bin/activate && "
           "python3 runs/agent/scheduler.py 2>&1 | tee ~/agent.log"]
    rc, _o, _e = _run(cmd, timeout=20)
    print(json.dumps({"ok": rc == 0, "msg": "agent restart issued"}))
    return 0 if rc == 0 else 1
def cmd_selfcheck():
    """自愈演练：kill agent tmux → 验证 supervisor 60s 内拉起（会短暂中断对话，仅授权时执行）。"""
    _run(["tmux", "kill-session", "-t", "agent"])
    t0 = time.time()
    ok = False
    while time.time() - t0 < 90:
        time.sleep(10)
        if session_alive("agent") and port_up(7860):
            ok = True
            break
    print(json.dumps({"ok": ok, "msg": "agent 自愈 " + ("成功" if ok else "超时")}))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="book-15 服务编排动作")
    ap.add_argument("cmd", choices=["status", "restart-llm", "restart-agent", "selfcheck"])
    args = ap.parse_args(argv)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "restart-llm":
        return cmd_restart_llm()
    if args.cmd == "restart-agent":
        return cmd_restart_agent()
    return cmd_selfcheck()


if __name__ == "__main__":
    raise SystemExit(main())
