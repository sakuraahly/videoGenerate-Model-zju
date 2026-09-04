#!/usr/bin/env python3
"""llm_mem — Qwen(SGLang) 与 ComfyUI 的内存协同（GB10 统一内存池）。

背景：DGX Spark 为统一内存（~121GB 可用），ComfyUI 常驻约 49GB（H3 模型+预留）。
若 SGLang 也以 0.55 份额预分配，两者叠加会挤爆/拖慢生成。方案：
  1) 降额启动：SGLang coexist 默认 mem-fraction=0.40、context=16384（见
     shell/start_sglang_coexist.sh / llm_mem 配置），保证两者同时常驻还有余量；
  2) 运行时让位（nap/wake）：agent 成功提交 ComfyUI 生成任务后（assistant 文本含
     TASK_SUBMITTED）自动 nap——优雅停止 SGLang，把 ~40-50GB 让给视频生成；
     下一轮对话开始时自动 wake（重新拉起 SGLang 并等待就绪），agent 工作不受影响，
     只是唤醒需要约 1-3 分钟加载。

用法：
  python3 runs/agent/llm_mem.py status
  python3 runs/agent/llm_mem.py nap          # 停止 SGLang（不动 ComfyUI/agent 进程）
  python3 runs/agent/llm_mem.py wake         # 重新启动 SGLang 并等待就绪
  python3 runs/agent/llm_mem.py flush        # 仍在运行时清空 KV 缓存（可选手动）
配置：config/llm_mem.json（机器配置，两端各自维护；缺失=默认开启）
  {"enabled": true, "mem_fraction": 0.40, "context_length": 16384}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
))
CFG_FILE = PROJECT_ROOT / 'config' / 'llm_mem.json'
DEFAULT_CFG = {'enabled': True, 'mem_fraction': 0.50, 'context_length': 8192}
HEALTH_URL = 'http://127.0.0.1:8000/v1/models'
NAPKILL_FINISHED = 'llm_mem_nap_done'  # 供测试/日志识别


def _log(text: str) -> None:
    # book-11：关键事件入库（logutil 单一 Writer，进程内同 H3_LOG_FILE）；保留一行 stdout
    try:
        if str(PROJECT_ROOT / 'runs') not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT / 'runs'))
        from h3 import logutil
        logutil.ensure_run_log(PROJECT_ROOT, 'llm-mem')
        logutil.log_event('llm-mem', text)
    except Exception:  # noqa: BLE001
        pass
    print(f'[llm_mem] {text}')


def load_cfg() -> dict:
    try:
        cfg = json.loads(CFG_FILE.read_text(encoding='utf-8-sig'))
        return {**DEFAULT_CFG, **cfg}
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_CFG)


def is_up(timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(HEALTH_URL),
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _tmux_kill(name: str) -> None:
    subprocess.run(['tmux', 'kill-session', '-t', name],
                   capture_output=True, text=True)


def nap() -> int:
    """优雅停止 SGLang（释放其常驻内存给 ComfyUI/系统）。不动其它进程。"""
    if not is_up(2):
        _log('SGLang 本就没在运行，跳过 nap')
        return 0
    _log('nap: 停止 SGLang 以让位视频生成……')
    _tmux_kill('sglang')
    subprocess.run(['pkill', '-f', 'sglang.launch_server'],
                   capture_output=True, text=True)
    for _ in range(30):
        if not is_up(1):
            break
        time.sleep(1)
    if is_up(1):
        _log('nap 警告：SGLang 仍在响应（进程可能改名），未完全释放')
        return 2
    _log(f'nap 完成（{NAPKILL_FINISHED}）：内存已让位，下一轮对话会自动 wake）')
    return 0


def wake(timeout_s: int = 900, progress=None) -> int:
    """拉起 SGLang（coexist 降额配置）并等待就绪。"""
    if is_up(2):
        _log('SGLang 已在运行，跳过 wake')
        return 0
    cfg = load_cfg()
    start_script = PROJECT_ROOT / 'shell' / 'start_sglang_coexist.sh'
    if not start_script.exists():
        _log(f'错误：找不到 {start_script}')
        return 3
    _log(f'wake: 启动 SGLang（mem={cfg["mem_fraction"]} ctx={cfg["context_length"]}）……')
    _tmux_kill('sglang')
    env = dict(os.environ)
    env['PATH'] = (str(Path.home() / 'Qwen3.8-27B' / 'sglang-venv' / 'bin')
                   + os.pathsep + env.get('PATH', ''))
    env['SGLANG_MEM'] = str(cfg['mem_fraction'])
    env['SGLANG_CTX_LEN'] = str(cfg['context_length'])
    subprocess.Popen(
        ['tmux', 'new-session', '-d', '-s', 'sglang',
         f'cd {PROJECT_ROOT} && bash shell/start_sglang_coexist.sh '
         '2>&1 | tee ~/sglang.log'],
        env=env)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if is_up(3):
            _log(f'wake 完成（{int(time.time() - t0)}s）')
            return 0
        if progress:
            progress(int(time.time() - t0))
        time.sleep(5)
    _log('wake 超时：SGLang 未就绪，请看 ~/sglang.log')
    return 2


def flush() -> int:
    if not is_up(2):
        _log('SGLang 未在运行')
        return 0
    try:
        req = urllib.request.Request('http://127.0.0.1:8000/flush_cache',
                                     method='POST')
        with urllib.request.urlopen(req, timeout=30) as r:
            _log(f'flush_cache -> HTTP {r.status}')
        return 0
    except Exception as e:  # noqa: BLE001
        _log(f'flush_cache 失败: {e}')
        return 2


def maybe_nap_after(text: str) -> bool:
    """回合文本确认成功提交了真实生成任务(TASK_SUBMITTED) 且非 dry_run → nap。

    仅在无状态回合结束后调用（此时模型已输出完毕，杀服务不影响本轮）。
    """
    if 'TASK_SUBMITTED:' not in (text or ''):
        return False
    if not load_cfg().get('enabled', True):
        _log('已由 config/llm_mem.json 禁用自动让位')
        return False
    rc = nap()
    return rc == 0


def ensure_llm_up(timeout_s: int = 900, progress=None) -> bool:
    """对话开始前保证模型可用：SGLang 未在跑则自动 wake。"""
    if is_up(2):
        return True
    _log('检测到 SGLang 未运行，自动 wake……')
    return wake(timeout_s=timeout_s, progress=progress) == 0


def cmd_status() -> int:
    cfg = load_cfg()
    print(f'状态: {"运行中" if is_up() else "已停止/未启动"}')
    print(f'配置: {json.dumps(cfg, ensure_ascii=False)}  配置路径: {CFG_FILE}')
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Qwen(SGLang) 与 ComfyUI 内存协同')
    ap.add_argument('cmd', choices=['status', 'nap', 'wake', 'flush'])
    ap.add_argument('--timeout', type=int, default=900)
    args = ap.parse_args(argv)
    if args.cmd == 'status':
        return cmd_status()
    if args.cmd == 'nap':
        return nap()
    if args.cmd == 'wake':
        return wake(timeout_s=args.timeout)
    if args.cmd == 'flush':
        return flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
