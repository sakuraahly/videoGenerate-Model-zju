# -*- coding: utf-8 -*-
"""sglang_guard — SGLang 存活保障守护（book-19 §14；用户提议“自动监控+自动修复整合”）。

职责（周期循环）：
  1) 健康探测（端口 8000 + /v1/models）；
  2) 不健康时检查 ComfyUI GPU 占用（compute-apps）：占用高（≥阈值）→ 等待（记日志，
     不硬启——与 ComfyUI 共存需要其驻留释放）；占用低 → 自动拉起（低开销参数组合）；
  3) 拉起后验证；失败防抖（10 分钟内最多一次）。

用法：
  python runs/agent/sglang_guard.py once                    # 单次决策（可拉起）
  python runs/agent/sglang_guard.py loop [--interval 60] [--comfy-max-gb 32]
  # 常驻守护（建议 tmux: tmux new-session -d -s guard '... loop'）

配置：SGLANG_MEM（默认 0.40）、SGLANG_SPEC=off、SGLANG_MAX_RUN=1（共存低耗）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PORT = 8000
LOG = PROJECT_ROOT / "logs" / "sglang_guard.log"
COMFY_PID_MATCH = ("main.py", "--port", "8188")


def log(msg: str) -> None:
    line = "[%s] sglang_guard %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def port_up(port: int = PORT) -> bool:
    try:
        import socket
        s = socket.socket()
        s.settimeout(1.0)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def llm_up() -> bool:
    """SGLang 可用性：端口 + /v1/models（快速）。"""
    if not port_up():
        return False
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % PORT, timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def comfy_gpu_gb() -> Optional[float]:
    """ComfyUI CUDA 占用（GB）。解析 nvidia-smi --query-compute-apps；异常返回 None。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=6)
        total_mib = 0.0
        for ln in (r.stdout or "").splitlines():
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) >= 2:
                num = parts[1].split()[0]
                try:
                    total_mib += float(num)
                except ValueError:
                    continue
        return round(total_mib / 1024.0, 2) or None
    except Exception:  # noqa: BLE001
        return None


def decide(ping: bool, comfy_gb: Optional[float], threshold: float = 32.0) -> Tuple[str, str]:
    """决策（纯函数，可单测）：ok / wait（Comfy 占资源需等）/ start（可拉起）。

    ping=True→ok；ping=False 且 comfy_gb 未知→wait（不硬启）；comfy_gb≥阈值→wait；
    否则→start。
    """
    if ping:
        return "ok", "sglang 健康"
    if comfy_gb is None:
        return "wait", "无法读取 ComfyUI 占用（不硬启）"
    if comfy_gb >= threshold:
        return "wait", "ComfyUI 占用 %.1fGB（≥阈值 %.1fGB），等待释放" % (comfy_gb, threshold)
    return "start", "ComfyUI 占用 %.1fGB，可共存启动" % comfy_gb


def start_sglang(mem: str = None, spec: str = "off", max_run: str = "1") -> bool:
    """tmux 启动 SGLang（共存低耗参数）；返回是否已发启动。"""
    script = str(PROJECT_ROOT / "shell" / "start_sglang_coexist.sh")
    env = ("SGLANG_MEM=%s SGLANG_SPEC=%s SGLANG_MAX_RUN=%s "
           % (mem or "0.40", spec, max_run))
    cmd = "tmux new-session -d -s sglang '%s cd %s && %sbash %s 2>&1 | tee ~/sglang.log'" % (
        "bash -c", str(PROJECT_ROOT), env, script)
    try:
        subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
        log("start issued: mem=%s spec=%s max_run=%s" % (mem or "0.40", spec, max_run))
        return True
    except Exception as e:  # noqa: BLE001
        log("start failed: %s" % e)
        return False


def wait_up(timeout: int = 300) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if llm_up():
            return True
        time.sleep(10)
    return False


def run_once(threshold: float = 32.0) -> int:
    st, msg = decide(llm_up(), comfy_gpu_gb(), threshold)
    log("once decision=%s %s" % (st, msg))
    if st == "start":
        start_sglang()
        ok = wait_up(300)
        log("after start up=%s" % ok)
        return 0 if ok else 1
    return 0


def loop(interval: int = 60, threshold: float = 32.0) -> int:
    last_start = 0.0
    while True:
        try:
            st, msg = decide(llm_up(), comfy_gpu_gb(), threshold)
            if st == "ok":
                log("loop ok")
            elif st == "wait":
                log("loop %s" % msg)
            else:
                if time.monotonic() - last_start < 600:  # 防抖：10 分钟内一次
                    log("loop start deferred (recent attempt)")
                else:
                    last_start = time.monotonic()
                    log("loop starting sglang")
                    start_sglang()
        except Exception as e:  # noqa: BLE001
            log("loop error: %s" % e)
        time.sleep(interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SGLang 存活保障守护")
    ap.add_argument("mode", choices=["once", "loop"])
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--comfy-max-gb", type=float, default=32.0)
    args = ap.parse_args(argv)
    if args.mode == "once":
        return run_once(threshold=args.comfy_max_gb)
    return loop(interval=args.interval, threshold=args.comfy_max_gb)


if __name__ == "__main__":
    sys.exit(main())
