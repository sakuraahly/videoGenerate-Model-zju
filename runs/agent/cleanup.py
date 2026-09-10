#!/usr/bin/env python3
"""cleanup — 项目统一清理（日志 / 临时目录 / 工作流残留 / ComfyUI 中间产物 / 卡死进程）。

目标（2026-09-10 用户要求）：把"日志等占空间的东西"可一键清理，且**绝不误删交付物**。
与既有 session_cleanup.py 分工：本工具管运行期垃圾；会话聊天档仍由 session_cleanup 管。

安全红线（默认永不触碰）：
  · uploads/（素材）、outputs/（交付产物）、assets/、models/、venv、.git、config/
  · 每个目标都限定白名单根目录 + glob；删除前二次校验 realpath 前缀
  · 默认 **dry-run**（只报告）；--apply 才真删

用法（spark / agent run_script）：
  python3 runs/agent/cleanup.py --status                 # 只看占用与将清理项
  python3 runs/agent/cleanup.py --apply                  # 执行（日志/临时/工作流/pycache）
  python3 runs/agent/cleanup.py --apply --include-comfy  # 额外清理 ComfyUI output/video 旧产物
  python3 runs/agent/cleanup.py --apply --kill-stuck     # 额外清理卡死进程（>2h 的 ffmpeg/cosy）
  python3 runs/agent/cleanup.py --json                   # 机器可读输出
保留策略（可调）：日志保留最近 200 个且 3 天内；workflows 目录保留最近 100；
ComfyUI 产物保留最近 150；/tmp 项目临时文件保留 1 天内。
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOME = Path.home()
TMP = Path('/tmp')

# 允许清理的根目录（越界即拒绝）
ALLOWED_ROOTS = [str(ROOT / 'logs'), str(ROOT / 'workflows'), str(ROOT),
                 str(TMP), str(HOME / 'ai' / 'ComfyUI' / 'output')]

# 永不触碰
PROTECTED = ('/uploads/', '/outputs/', '/assets/', '/models/', '/.git/', '/config/',
             '/runs/', '/docs/', '/studio/')

DEFAULT_KEEP_LOGS = 200
DEFAULT_KEEP_LOG_DAYS = 3
DEFAULT_KEEP_WORKFLOWS = 100
DEFAULT_KEEP_COMFY = 150
DEFAULT_KEEP_TMP_DAYS = 1


def _human(n: float) -> str:
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024:
            return '%.1f%s' % (n, u)
        n /= 1024.0
    return '%.1fPB' % n


def _norm(path) -> str:
    """路径规范化：统一斜杠（Windows 反斜杠会让保护规则失效——2026-09-10 单测抓到）。"""
    return str(path).replace('\\', '/')


def _under_allowed(p: Path, kind: str = '') -> bool:
    """白名单根 + 保护路径二次校验（kind=pycache 允许位于受保护目录内）。"""
    rp = _norm(Path(p).resolve())
    if any(x in rp + '/' for x in PROTECTED):
        if not (kind == 'pycache' and '/__pycache__' in rp):
            return False
    return any(rp.startswith(_norm(r)) for r in ALLOWED_ROOTS)


def _size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        total = 0
        for dp, _dn, fn in os.walk(p):
            for f in fn:
                try:
                    total += (Path(dp) / f).stat().st_size
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def _dir_size(paths) -> int:
    return sum(_size(p) for p in paths)


def collect_logs(keep: int, keep_days: int) -> list:
    out = []
    files = sorted(_glob.glob(str(ROOT / 'logs' / 'run_*.log')), key=os.path.getmtime, reverse=True)
    for i, f in enumerate(files):
        p = Path(f)
        age_days = (time.time() - os.path.getmtime(f)) / 86400.0
        if i >= keep and age_days > keep_days:
            out.append((p, 'log'))
    # 超大滚动日志：截断保留尾部（不整删，保最近现场）
    for name in ('agent-tasks.state.sched.log', 'agent-tasks.log'):
        p = ROOT / 'logs' / name
        if p.is_file() and p.stat().st_size > 20 * 1024 * 1024:
            out.append((p, 'truncate'))
    return out


def collect_workflows(keep: int) -> list:
    out = []
    dirs = [Path(d) for d in _glob.glob(str(ROOT / 'workflows' / 'h3_*')) if os.path.isdir(d)]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        out.append((d, 'workflow'))
    return out


def collect_tmp(keep_days: int) -> list:
    out = []
    patterns = ['lipsync_chain', 'story_film*', 'oil_story', 'film_stitch_*', 'talk_one',
                'echomimic*', 'h3_*', 'attach_only*', 'amix_sil*', 'om_*', 'v*_clean*',
                'v6_*', 'v7_*', 'v8_*', 'demo_*', 'cat_*', 'seg*_job*', 'subq*.py',
                'stub_argv.py', 'probe_*', 'loud_*', 'rt*.log', 'oil_send.json',
                # 2026-09-10 扩展（实测 /tmp 大头）：GFPGAN 中间帧、pip 安装残留、修复帧
                'gfp_frames*', 'pip-install-*', 'pip-unpack-*', 'w2l_*', 'lipsync_*']
    seen = set()
    for pat in patterns:
        for f in _glob.glob(str(TMP / pat)):
            p = Path(f)
            if p in seen:
                continue
            seen.add(p)
            age = (time.time() - p.stat().st_mtime) / 86400.0 if p.exists() else 0
            if age > keep_days:
                out.append((p, 'tmp'))
    return out


def collect_pycache() -> list:
    out = []
    for dp, dn, _fn in os.walk(ROOT):
        if '.git' in dp or 'node_modules' in dp:
            continue
        for d in list(dn):
            if d == '__pycache__':
                out.append((Path(dp) / d, 'pycache'))
    return out


def collect_comfy(keep: int) -> list:
    out = []
    files = sorted(_glob.glob(str(HOME / 'ai' / 'ComfyUI' / 'output' / 'video' / '*.mp4')),
                   key=os.path.getmtime, reverse=True)
    for f in files[keep:]:
        out.append((Path(f), 'comfy'))
    # ComfyUI 临时目录
    for f in _glob.glob(str(HOME / 'ai' / 'ComfyUI' / 'temp' / '*')):
        p = Path(f)
        if (time.time() - p.stat().st_mtime) / 86400.0 > 1:
            out.append((p, 'comfy_tmp'))
    return out


def stuck_procs(min_hours: float = 2.0) -> list:
    """报告运行时长超阈值的 ffmpeg / cosy / h3_submit 残留（可能卡死）。"""
    out = []
    try:
        ps = subprocess.run(['ps', '-eo', 'pid,etimes,cmd'], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return out
    for line in (ps.stdout or '').splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, cmd = parts[0], parts[1], parts[2]
        try:
            et = int(etimes)
        except ValueError:
            continue
        if et < min_hours * 3600:
            continue
        if any(k in cmd for k in ('ffmpeg', 'tts_cosy_check', 'h3_submit.py', 'wav2lip')):
            if 'cleanup.py' in cmd or 'grep' in cmd:
                continue
            out.append({'pid': int(pid), 'hours': round(et / 3600.0, 1), 'cmd': cmd[:120]})
    return out


def build_plan(args) -> dict:
    items = []
    items += collect_logs(args.keep_logs, args.keep_log_days)
    items += collect_workflows(args.keep_workflows)
    items += collect_tmp(args.keep_tmp_days)
    items += collect_pycache()
    if args.include_comfy:
        items += collect_comfy(args.keep_comfy)
    # 越界/保护二次校验
    safe = [(p, k) for (p, k) in items if _under_allowed(p, k)]
    plan = {
        'items': safe,
        'skipped_protected': [str(p) for (p, _k) in items if not _under_allowed(p, _k)],
        'total_bytes': sum(_size(p) for p, _k in safe),
        'stuck': stuck_procs(),
    }
    return plan


def cmd_status(args) -> int:
    plan = build_plan(args)
    by_kind = {}
    for p, k in plan['items']:
        by_kind.setdefault(k, [0, 0])
        by_kind[k][0] += 1
        by_kind[k][1] += _size(p)
    print('== 清理目标统计（dry-run，未删除任何文件）')
    for k, (n, sz) in sorted(by_kind.items()):
        print('  %-10s %4d 项  %s' % (k, n, _human(sz)))
    print('  合计: %d 项  %s' % (sum(v[0] for v in by_kind.values()), _human(plan['total_bytes'])))
    print('== 磁盘:')
    for mp in ('/', str(ROOT), '/tmp'):
        try:
            st = os.statvfs(mp)
            print('  %-28s 可用 %s / 总 %s' % (mp, _human(st.f_bavail * st.f_frsize),
                                               _human(st.f_blocks * st.f_frsize)))
        except OSError:
            pass
    if plan['stuck']:
        print('== 疑似卡死进程（--kill-stuck 可清理）:')
        for s in plan['stuck']:
            print('  pid=%s 已跑 %.1fh  %s' % (s['pid'], s['hours'], s['cmd']))
    if plan['skipped_protected']:
        print('== 受保护跳过 %d 项（uploads/outputs/assets/models/config 等）'
              % len(plan['skipped_protected']))
    if args.json:
        print(json.dumps({'by_kind': {k: [v[0], v[1]] for k, v in by_kind.items()},
                          'total_bytes': plan['total_bytes'], 'stuck': plan['stuck']},
                         ensure_ascii=False))
    return 0


def cmd_apply(args) -> int:
    plan = build_plan(args)
    freed = 0
    removed = 0
    failed = 0
    for p, kind in plan['items']:
        if not _under_allowed(p, kind):
            continue
        sz = _size(p)
        try:
            if kind == 'truncate':
                data = p.read_text(encoding='utf-8', errors='replace').splitlines()[-10000:]
                p.write_text('\n'.join(data) + '\n', encoding='utf-8')
                freed += max(0, sz - p.stat().st_size)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=False)
                freed += sz
            else:
                p.unlink()
                freed += sz
            removed += 1
        except OSError:
            failed += 1
    print('== 清理完成: 删除/截断 %d 项, 释放 %s%s'
          % (removed, _human(freed), (', 失败 %d' % failed) if failed else ''))
    if args.kill_stuck and plan['stuck']:
        killed = 0
        for s in plan['stuck']:
            try:
                os.kill(s['pid'], 9)
                killed += 1
            except OSError:
                pass
        print('== 卡死进程清理: %d 个' % killed)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser('项目统一清理（日志/临时/工作流/中间产物/卡死进程）')
    ap.add_argument('--status', action='store_true', help='只报告（默认动作）')
    ap.add_argument('--apply', action='store_true', help='执行清理（默认 dry-run）')
    ap.add_argument('--keep-logs', type=int, default=DEFAULT_KEEP_LOGS)
    ap.add_argument('--keep-log-days', type=int, default=DEFAULT_KEEP_LOG_DAYS)
    ap.add_argument('--keep-workflows', type=int, default=DEFAULT_KEEP_WORKFLOWS)
    ap.add_argument('--keep-tmp-days', type=int, default=DEFAULT_KEEP_TMP_DAYS)
    ap.add_argument('--keep-comfy', type=int, default=DEFAULT_KEEP_COMFY)
    ap.add_argument('--include-comfy', action='store_true',
                    help='一并清理 ComfyUI output/video 旧产物（保留最近 --keep-comfy 个）')
    ap.add_argument('--kill-stuck', action='store_true',
                    help='清理运行 >2 小时的 ffmpeg/cosy 残留进程')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    if args.kill_stuck:
        args.include_comfy = args.include_comfy  # 显式语义：kill 需与 apply 同用
    return cmd_apply(args) if args.apply else cmd_status(args)


if __name__ == '__main__':
    sys.exit(main())
