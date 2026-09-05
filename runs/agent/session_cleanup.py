#!/usr/bin/env python3
"""session_cleanup — 90 天历史会话自动清理（只删聊天档，绝不碰运行期产物）。

背景：logs/agent_chats/ 下每个会话存 <cid>.jsonl（对话）与 <cid>.meta.json
（run_log 互链 + ts + n_msgs，见 ui_app.save_chat）。长期累积需定期清理。
策略见 config/session_retention.json（全项目统一、入库 tracked，非机器配置）。

安全边界（红线，来自 handoff-2026-09-05-L-tasks.md §L1）：
  - 只删聊天档：<cid>.jsonl 与 <cid>.meta.json；
  - thumbs/<sha>.jpg 按内容 sha 命名、无法关联 cid → 一律不删（保守，避免误删
    其它会话仍在引用的缩略图）；
  - 严禁删 uploads/、workflows/、outputs/、logs/run_*.log（运行期产物）。

判定基准：文件 mtime 与 meta.ts 的**较新者**（取 max）——只要有一个信号说明
"最近动过"就不算超期，宁可漏删不可误删。

用法：
  python runs/agent/session_cleanup.py status            # 统计（总数/超期/保留）
  python runs/agent/session_cleanup.py clean             # dry-run 打印将删清单
  python runs/agent/session_cleanup.py clean --yes       # 真正删除超期会话
  python runs/agent/session_cleanup.py clean --days 30   # 覆盖保留天数
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
))
CHATS_DIR = PROJECT_ROOT / 'logs' / 'agent_chats'
CFG_FILE = PROJECT_ROOT / 'config' / 'session_retention.json'
DEFAULT_CFG = {'enabled': True, 'days': 90, 'dry_run': True}
TS_FMT = '%Y-%m-%d %H:%M:%S'   # 与 ui_app._now() 一致


def load_cfg() -> dict:
    """读 config/session_retention.json；缺失/损坏回退 DEFAULT_CFG。"""
    try:
        cfg = json.loads(CFG_FILE.read_text(encoding='utf-8-sig'))
        return {**DEFAULT_CFG, **cfg}
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_CFG)


def _meta_path(jsonl: Path) -> Path:
    return jsonl.with_suffix('.meta.json')


def _parse_ts(meta: Path):
    """读 meta.ts → datetime；失败返回 None。"""
    try:
        d = json.loads(meta.read_text(encoding='utf-8-sig'))
        ts = str(d.get('ts') or '')
        return datetime.strptime(ts, TS_FMT) if ts else None
    except Exception:  # noqa: BLE001
        return None


def age_basis(jsonl: Path, meta: Path, now: datetime) -> datetime:
    """判定基准 = 文件 mtime 与 meta.ts 的较新者（max）。

    两者都拿不到时返回 now（视作"刚动过"，不删——安全默认）。
    """
    candidates = []
    try:
        candidates.append(datetime.fromtimestamp(jsonl.stat().st_mtime))
    except OSError:
        pass
    if meta.exists():
        ts = _parse_ts(meta)
        if ts is not None:
            candidates.append(ts)
    if not candidates:
        return now
    return max(candidates)


def scan(chats_dir, days: int, now: datetime = None) -> dict:
    """扫描会话档 → {'total','expired','kept','sessions':[...]}。"""
    now = now or datetime.now()
    chats_dir = Path(chats_dir)
    result = {'total': 0, 'expired': 0, 'kept': 0, 'sessions': []}
    if not chats_dir.is_dir():
        return result
    cutoff = datetime.fromtimestamp(now.timestamp() - days * 86400)
    for jsonl in sorted(chats_dir.glob('*.jsonl')):
        meta = _meta_path(jsonl)
        basis = age_basis(jsonl, meta, now)
        expired = basis < cutoff
        result['total'] += 1
        result['expired' if expired else 'kept'] += 1
        result['sessions'].append({
            'cid': jsonl.stem, 'jsonl': jsonl, 'meta': meta,
            'basis': basis, 'expired': expired, 'has_meta': meta.exists(),
        })
    return result


def status(chats_dir=None, days=None) -> tuple:
    """统计会话保留情况；返回 (统计字典, exit_code)。"""
    cfg = load_cfg()
    days = cfg['days'] if days is None else days
    chats_dir = Path(chats_dir or CHATS_DIR)
    info = scan(chats_dir, days)
    stats = {
        'chats_dir': str(chats_dir), 'days': days,
        'enabled': cfg.get('enabled', True),
        'total': info['total'], 'expired': info['expired'], 'kept': info['kept'],
    }
    print(f"[session_cleanup] 目录: {stats['chats_dir']}")
    print(f"[session_cleanup] 保留天数: {days}  策略启用: {stats['enabled']}")
    print(f"[session_cleanup] 会话总数: {stats['total']}  "
          f"超期: {stats['expired']}  保留: {stats['kept']}")
    return stats, 0


def clean(chats_dir=None, days=None, dry_run=None, yes: bool = False) -> tuple:
    """删除超期会话档；返回 (统计字典, exit_code)。

    dry_run 缺省时 = not yes（无 --yes 即 dry-run，只打印将删清单）。
    只删 <cid>.jsonl 与 <cid>.meta.json；thumbs/<sha>.jpg 按内容 sha 命名、
    无法关联 cid → 一律不删（见模块 docstring 的安全边界）。
    """
    cfg = load_cfg()
    days = cfg['days'] if days is None else days
    if dry_run is None:
        dry_run = not yes
    chats_dir = Path(chats_dir or CHATS_DIR)
    info = scan(chats_dir, days)
    expired = [s for s in info['sessions'] if s['expired']]
    deleted = {'jsonl': 0, 'meta': 0, 'failed': 0}
    for s in expired:
        if dry_run:
            print(f"[dry-run] 将删: {s['jsonl'].name}"
                  + (f" + {s['meta'].name}" if s['has_meta'] else ''))
            continue
        try:
            s['jsonl'].unlink()
            deleted['jsonl'] += 1
        except OSError as e:
            deleted['failed'] += 1
            print(f"[session_cleanup] 删除失败 {s['jsonl'].name}: {e}")
            continue
        if s['has_meta']:
            try:
                s['meta'].unlink()
                deleted['meta'] += 1
            except OSError:
                pass
    stats = {
        'chats_dir': str(chats_dir), 'days': days, 'dry_run': dry_run,
        'total': info['total'], 'expired': len(expired), 'deleted': deleted,
    }
    mode = 'DRY-RUN（未删除）' if dry_run else '已删除'
    print(f"[session_cleanup] {mode}: 超期 {len(expired)} 个会话；"
          f"jsonl 删 {deleted['jsonl']}，meta 删 {deleted['meta']}，"
          f"失败 {deleted['failed']}")
    if dry_run and expired:
        print('[session_cleanup] 加 --yes 真正删除。thumbs/ 缩略图不删（无法关联 cid）。')
    return stats, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='90 天历史会话清理（只删聊天档）')
    ap.add_argument('cmd', choices=['status', 'clean'])
    ap.add_argument('--yes', action='store_true', help='clean 真正删除（默认 dry-run）')
    ap.add_argument('--days', type=int, default=None, help='覆盖保留天数（默认取配置 90）')
    args = ap.parse_args(argv)
    if args.cmd == 'status':
        _stats, rc = status(days=args.days)
        return rc
    if args.cmd == 'clean':
        _stats, rc = clean(days=args.days, yes=args.yes)
        return rc
    return 2


if __name__ == '__main__':
    sys.exit(main())
