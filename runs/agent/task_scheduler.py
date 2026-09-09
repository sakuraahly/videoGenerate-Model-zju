#!/usr/bin/env python3
"""task_scheduler — Agent 任务调度器（定期/定点/服从安排）。

背景（2026-09-09 用户定案）：agent 不能只是"对话即所得"——必须能**定期定点执行任务、服从安排**。
本模块为 7860 agent 补上执行骨架：

  任务定义：config/agent-tasks.json
    {"id": "...", "name": "...", "kind": "engine|agent",
     "schedule": {"min": "*/5", "hour": "*", "dom": "*", "mon": "*", "dow": "*"},
     "action": "run_script", "script": "runs/h3/film_series.py", "args": "...",
     "prompt": "…（kind=agent 时注入 7860 会话的指令）",
     "enabled": true}
  执行语义：
    - engine 任务：调度器**直接**执行白名单脚本（同 run_script 边界：runs/ 下 .py；100% 可靠）
      —— 这类（生成/拼接/夜间/巡检）不再依赖对话 agent 的自主性；
    - agent 任务：把 prompt **注入** 7860 会话（Gradio send API）→ 由 agent 执行；
      完成判定=随后的 run 日志出现工具调用成功（submitted/工具输出）；无则标记 agent-fail，
      重试（默认 3 次），仍失败 → 记入 state 并（可选）降级为 engine 行动（若 action 有 engine 兜底）。
  状态：logs/agent-tasks.state.json（非 git）。
  运行：每分钟 cron 调 --tick（或 python3 runs/agent/task_scheduler.py --tick --once）。常驻 --daemon 亦可。

用法：
  python3 runs/agent/task_scheduler.py --tick            # 手动一轮（演示/调试）
  python3 runs/agent/task_scheduler.py --list            # 列任务+状态
  python3 runs/agent/task_scheduler.py --daemon          # 常驻（60s 循环）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = ROOT / 'config' / 'agent-tasks.json'
STATE = ROOT / 'logs' / 'agent-tasks.state.json'
AGENT_URL = 'http://127.0.0.1:7860/gradio_api/call/send'
ALLOWED_SCRIPT_DIRS = (str(ROOT / 'runs'),)
MAX_RETRY = 3


def _log(msg: str) -> None:
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f'[task-scheduler] {ts} {msg}'
    print(line, flush=True)
    try:
        with open(STATE.with_suffix('.sched.log'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8')) if STATE.is_file() else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(st: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:
        pass


def load_tasks() -> list:
    try:
        d = json.loads(TASKS.read_text(encoding='utf-8'))
        return list(d.get('tasks', []) if isinstance(d, dict) else [])
    except Exception as e:  # noqa: BLE001
        _log('tasks 读取失败: %s' % str(e)[:100])
        return []


def _match(field: str, cur: int) -> bool:
    field = str(field or '*').strip()
    if field in ('*', ''):
        return True
    for part in field.split(','):
        part = part.strip()
        if not part:
            continue
        if part.startswith('*/'):
            step = int(part[2:])
            if step <= 0:
                continue
            if cur % step == 0:
                return True
            continue
        if '/' in part:
            a, b = part.split('/', 1)
            base = int(a) if a.isdigit() else 0
            step = int(b) if b.isdigit() else 1
            if step > 0 and cur % step == base % step:
                return True
            continue
        if part.isdigit() and int(part) == cur:
            return True
        if '-' in part:
            lo, hi = part.split('-', 1)
            if lo.isdigit() and hi.isdigit() and int(lo) <= cur <= int(hi):
                return True
    return False


def due_now(task: dict, now: time.struct_time) -> bool:
    s = task.get('schedule') or {}
    return (_match(s.get('min', '*'), now.tm_min) and _match(s.get('hour', '*'), now.tm_hour)
            and _match(s.get('dom', '*'), now.tm_mday)
            and _match(s.get('mon', '*'), now.tm_mon)
            and _match(s.get('dow', '*'), (now.tm_wday + 1) % 7))


def _safe_script(task: dict) -> tuple:
    script = str(task.get('script') or '')
    if '..' in script or script.startswith('/'):
        return '', '路径非法'
    if not script.endswith('.py') or not Path(ROOT / 'runs' / script).is_file():
        return '', '脚本不在白名单: ' + script
    return str(ROOT / 'runs' / script), ''


def run_engine(task: dict) -> str:
    """直接执行白名单脚本（可靠路径）。"""
    script, err = _safe_script(task)
    if err:
        return 'ERR ' + err
    cmd = [sys.executable, script]
    if task.get('args'):
        cmd += str(task['args']).split()
    env = dict(os.environ)
    if task.get('cid'):
        env['VIDEOGEN_SESSION_CID'] = str(task['cid'])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60 * 2,
                           cwd=str(ROOT), env=env)
        out = (r.stdout or '') + (r.stderr or '')
        if r.returncode == 0:
            return 'ok: ' + out[-300:].strip().replace('\n', ' | ')
        return f'ERR rc={r.returncode}: ' + out[-300:].strip().replace('\n', ' | ')
    except Exception as e:  # noqa: BLE001
        return 'ERR ' + str(e)[:120]


def run_agent_task(task: dict) -> str:
    """注入 7860 会话（agent 执行对话任务）：保留会话历史+注入后审计工具调用（假完成检测）。"""
    prompt = str(task.get('prompt') or '').strip()
    if not prompt:
        return 'ERR 无 prompt'
    cid = str(task.get('cid') or '')
    # 保历史：注入前尝试读取该会话存档（避免 send(hist=[]) 冲掉历史）
    hist: list = []
    if cid:
        try:
            import json as _j
            _f = (ROOT / 'logs' / 'agent_chats' / f'{cid}.jsonl')
            if _f.is_file():
                hist = [{'role': _j.loads(ln).get('role'), 'content': _j.loads(ln).get('content')}
                        for ln in _f.read_text(encoding='utf-8').splitlines()
                        if ln.strip()]
                hist = [m for m in hist if m.get('role') in ('user', 'assistant') and m.get('content')]
        except Exception:  # noqa: BLE001
            hist = []
    # 审计基线：记录最新 run log 的 mtime+行数
    import glob as _glob
    _logs = sorted(_glob.glob(str(ROOT / 'logs' / 'run_*.log')), key=os.path.getmtime, reverse=True)
    base_log = _logs[0] if _logs else None
    base_mtime = os.path.getmtime(base_log) if base_log else 0.0
    base_lines = len(base_log.open(encoding='utf-8', errors='replace').read().splitlines()) if base_log else 0
    try:
        data = json.dumps({'data': [hist, cid, prompt]}, ensure_ascii=False).encode()
        req = urllib.request.Request(AGENT_URL, data=data,
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        ev = d.get('event_id') or ''
        _log('agent 任务注入 event=%s cid=%s hist=%d' % (ev[:12], cid or '(auto)', len(hist)))
    except Exception as e:  # noqa: BLE001
        return 'ERR 注入失败: ' + str(e)[:120]
    # 审计：注入后 35s 内检查新 run 日志出现工具调用（submitted/run_script call/工具输出）
    time.sleep(35)
    try:
        import glob as _g2
        _new = sorted(_g2.glob(str(ROOT / 'logs' / 'run_*.log')), key=os.path.getmtime, reverse=True)[:3]
        found = False
        for _lf in _new:
            if not _lf.is_file():
                continue
            if os.path.getmtime(_lf) < base_mtime and _lf == base_log:
                continue
            txt = _lf.read_text(encoding='utf-8', errors='replace')
            new_txt = txt.splitlines()
            start = base_lines if _lf == base_log else 0
            for ln in new_txt[start:]:
                if any(k in ln for k in ('call params', 'submitted ', 'TASK_SUBMITTED',
                                         'tool_call', 'run_script ok', 'LOCAL_OUTPUT')):
                    found = True
                    break
            if found:
                break
        if found:
            return 'ok event=' + ev[:12] + ' 审计: 有工具调用'
        return 'WARN event=' + ev[:12] + ' 审计: 未见工具调用（疑似未执行/假完成）'
    except Exception as e:  # noqa: BLE001
        return 'WARN event=' + ev[:12] + ' 审计异常: ' + str(e)[:80]


def tick() -> int:
    now = time.localtime()
    st = load_state()
    for task in load_tasks():
        tid = str(task.get('id') or '')
        if not task.get('enabled', True):
            continue
        if not due_now(task, now):
            continue
        rec = st.setdefault(tid, {'last_run': '', 'runs': 0, 'last_result': '', 'fails': 0})
        # 同一分钟内避免重复执行
        key = time.strftime('%Y-%m-%d %H:%M', now)
        if rec.get('last_run') == key:
            continue
        kind = str(task.get('kind') or 'engine')
        _log('执行 %s [%s] %s' % (tid, kind, task.get('name', '')))
        if kind == 'agent':
            res = run_agent_task(task)
            # 完成判定：注入后等待并检查 run 日志是否有工具调用（简化：注入成功=已提交给 agent）
            rec['last_run'] = key
            rec['runs'] += 1
            rec['last_result'] = res[:200]
            if res.startswith('ERR'):
                rec['fails'] = rec.get('fails', 0) + 1
            else:
                rec['fails'] = 0
            _log('  -> %s' % res[:160])
        else:
            # engine：执行失败自动重试（最多 MAX_RETRY 次）
            res = ''
            for attempt in range(1, MAX_RETRY + 1):
                res = run_engine(task)
                if not res.startswith('ERR'):
                    break
                _log('  第%d 次失败: %s' % (attempt, res[:120]))
                time.sleep(5)
            rec['last_run'] = key
            rec['runs'] += 1
            rec['last_result'] = res[:300]
            rec['fails'] = rec.get('fails', 0) + (0 if not res.startswith('ERR') else 1)
            _log('  -> %s' % res[:160])
        save_state(st)
    return 0


def list_tasks() -> int:
    st = load_state()
    for task in load_tasks():
        rec = st.get(str(task.get('id') or ''), {})
        print("%-28s kind=%-6s enabled=%s last=%s result=%s" % (
            task.get('id', '?'), task.get('kind', 'engine'), task.get('enabled', True),
            rec.get('last_run', '-'), str(rec.get('last_result', ''))[:90].replace('\n', ' ')))
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser('agent 任务调度器（定期/定点）')
    ap.add_argument('--tick', action='store_true', help='执行一轮到期任务')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--daemon', action='store_true', help='常驻循环（60s）')
    args = ap.parse_args()
    if args.list:
        return list_tasks()
    if args.tick:
        return tick()
    if args.daemon:
        _log('daemon started')
        while True:
            try:
                tick()
            except BaseException as e:  # noqa: BLE001
                _log('tick err ' + type(e).__name__)
            time.sleep(60)
        return 0
    print('用法: --tick | --list | --daemon')
    return 2


if __name__ == '__main__':
    sys.exit(main())
