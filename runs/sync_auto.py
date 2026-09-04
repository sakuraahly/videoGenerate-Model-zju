#!/usr/bin/env python3
"""sync_auto — “两个文件夹自动化合并”开关与执行器（Windows ↔ spark）。

背景：项目同时在 Windows 本机与 spark（~/videoGenerate-Model-zju）维护；两端 git
历史不互通（spark 只留本地 git），文件同步走 runs/sync_merge.py 的“逐文件取新 +
显式冲突”。本工具把该合并过程做成**可手动开启/关闭的自动化**：

- enable   ：写入 config/autosync.json enabled=true 并（可选 --daemon）后台启动
              watch 循环（按 interval 秒周期执行合并一轮）
- disable  ：enabled=false（watch 循环会在下一轮自然退出）
- once     ：立即执行一轮合并（不依赖开关）
- status   ：查看开关/配置/最近一轮结果
- watch    ：前台循环模式（Ctrl+C 退出；enable --daemon 在后台静默跑它）

每轮合并（merge_round）：
  1. 在 win-remote 侧运行 runs/sync_merge.py --status 记录差异摘要；
  2. 依次执行 --push-auto（本地新 → 远端）与 --pull-auto（远端新 → 本地），
     实现“逐文件取较新端”，两端同时改动=冲突 → 不自动覆盖，留在冲突清单；
  3. 结果（含冲突清单）追加到 logs/sync_auto.log。

模式隔离：仅当本机 config/deploy.json site=win-remote（仓库在本机、经 ssh 访问
spark）时执行；spark-local（仓库在 spark）侧不自动发起（spark 无 ssh 回本机的
通道），提示由本机侧开启。删除一律不自动（沿用 sync_merge 的 delete_note 纪律）。

用法示例：
  python runs/sync_auto.py status
  python runs/sync_auto.py once
  python runs/sync_auto.py enable --daemon --interval 180
  python runs/sync_auto.py disable
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "autosync.json"
LOG = ROOT / "logs" / "sync_auto.log"
DEFAULT = {"enabled": False, "interval": 180, "last_run": "", "last_summary": ""}
_EXCLUDE_NOTE = "（config/autosync.json 为两端各自维护的机器配置，不同步）"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(text: str) -> None:
    # book-11：统一格式（logutil 单一 Writer）写 logs/sync_auto.log；保留 stdout 供 agent.log
    try:
        import sys as _sys
        if str(ROOT / "runs") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "runs"))
        from h3 import logutil
        logutil.log_file(str(LOG), "sync-auto", text)
    except Exception:  # noqa: BLE001
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"[{_now()}] py: sync-auto {text}\n")
        except OSError:
            pass
    print(f"[sync_auto] {text}")


def load_cfg() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        return {**DEFAULT, **cfg}
    except Exception:  # noqa: BLE001
        return dict(DEFAULT)


def save_cfg(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def _site() -> str:
    try:
        dep = json.loads((ROOT / "config" / "deploy.json").read_text(encoding="utf-8-sig"))
        return str(dep.get("site") or "win-remote")
    except Exception:  # noqa: BLE001
        return "win-remote"


def _run_sync_merge(argv) -> str:
    sm = ROOT / "runs" / "sync_merge.py"
    r = subprocess.run([sys.executable, str(sm)] + argv,
                       capture_output=True, text=True, timeout=240, cwd=str(ROOT))
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return out


def merge_round(force: bool = False) -> dict:
    """执行一轮合并；返回 {ok, summary, conflicts}。"""
    if not force and _site() == "spark-local":
        return {"ok": False,
                "summary": "spark-local：仓库在 spark 上，请在本机(win-remote)侧开启自动合并"
                           + _EXCLUDE_NOTE,
                "conflicts": []}
    _log("合并轮开始……")
    status_before = _run_sync_merge(["--status"])
    _run_sync_merge(["--push-auto"])
    _run_sync_merge(["--pull-auto"])
    status_after = _run_sync_merge(["--status"])
    conflicts = [ln for ln in status_after.splitlines()
                 if "冲突" in ln or "conflict" in ln.lower()]
    _log("合并轮完成。")
    return {"ok": True, "summary": status_before.splitlines()[:3]
            + ["→ 合并后:"]
            + status_after.splitlines()[:6],
            "conflicts": conflicts[:10]}


def cmd_status() -> int:
    cfg = load_cfg()
    print(f"开关: {'开启' if cfg['enabled'] else '关闭'}")
    print(f"周期: {cfg['interval']}s    最近运行: {cfg['last_run'] or '从未'}")
    print(f"最近摘要: {cfg['last_summary'] or '无'}")
    if LOG.exists():
        print("--- 最近日志 ---")
        print("\n".join(LOG.read_text(encoding="utf-8").splitlines()[-6:]))
    return 0


def cmd_enable(interval: int, daemon: bool) -> int:
    cfg = load_cfg()
    cfg["enabled"] = True
    cfg["interval"] = int(interval)
    save_cfg(cfg)
    _log(f"已开启自动合并（interval={interval}s）" + _EXCLUDE_NOTE)
    if daemon:
        # 后台静默运行 watch（Windows 下用 pythonw 避免黑窗口）
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(exe):
            exe = sys.executable
        subprocess.Popen([exe, str(Path(__file__).resolve()), "watch"],
                         cwd=str(ROOT),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _log("watch 已后台启动")
    return 0


def cmd_disable() -> int:
    cfg = load_cfg()
    cfg["enabled"] = False
    save_cfg(cfg)
    _log("已关闭自动合并（watch 将在下一轮退出）")
    return 0


def cmd_watch(interval: int) -> int:
    _log(f"watch 模式启动（interval={interval}s，Ctrl+C 退出）")
    try:
        while True:
            cfg = load_cfg()
            if not cfg["enabled"]:
                _log("开关已关闭，watch 退出")
                break
            iv = int(cfg.get("interval") or interval)
            res = merge_round()
            cfg = load_cfg()
            cfg["last_run"] = _now()
            cfg["last_summary"] = "；".join(str(x) for x in res["summary"])[:500]
            save_cfg(cfg)
            if res["conflicts"]:
                _log("冲突待人工处理: " + " | ".join(res["conflicts"]))
            time.sleep(iv)
    except KeyboardInterrupt:
        _log("watch 被手动中断")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="两个文件夹自动化合并开关/执行器")
    ap.add_argument("cmd", choices=["enable", "disable", "status", "once", "watch"])
    ap.add_argument("--interval", type=int, default=180, help="watch 周期秒")
    ap.add_argument("--daemon", action="store_true", help="enable 时后台启动 watch")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "enable":
        return cmd_enable(args.interval, args.daemon)
    if args.cmd == "disable":
        return cmd_disable()
    if args.cmd == "once":
        res = merge_round(force=True)
        cfg = load_cfg()
        cfg["last_run"] = _now()
        cfg["last_summary"] = "；".join(str(x) for x in res["summary"])[:500]
        save_cfg(cfg)
        for ln in res["summary"]:
            print("  " + str(ln))
        if res["conflicts"]:
            print("冲突待人工处理（sync_merge.py --resolve）:")
            for c in res["conflicts"]:
                print("  " + c)
        _log("once 执行结束")
        return 0 if res["ok"] else 3
    if args.cmd == "watch":
        return cmd_watch(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
