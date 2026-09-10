#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_cleanup.py — 清理程序纯逻辑单测（不删真实文件；一切在临时目录内）。"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.agent import cleanup as cl  # noqa: E402


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL:', msg)
        else:
            print('ok:', msg)

    # 1) 保护路径校验：交付物/素材/配置绝不可删；日志与 pycache 可删
    check(not cl._under_allowed(ROOT / 'outputs' / 'video_99.mp4'), 'outputs 交付物受保护')
    check(not cl._under_allowed(ROOT / 'uploads' / '20260906' / 'x.png'), 'uploads 素材受保护')
    check(not cl._under_allowed(ROOT / 'config' / 'pipeline.json'), 'config 受保护')
    check(cl._under_allowed(ROOT / 'logs' / 'run_2026.log'), 'logs 运行日志可清理')
    check(cl._under_allowed(ROOT / 'runs' / 'agent' / '__pycache__', 'pycache'), 'pycache 可清理（豁免）')
    check(not cl._under_allowed(ROOT / 'runs' / 'agent' / 'cleanup.py'), '源码不可删')

    # 2) 日志保留策略：保留最近 N 个且 N 天内
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / 'logs'
        base.mkdir(parents=True)
        old = time.time() - 10 * 86400
        for i in range(5):
            f = base / ('run_%d.log' % i)
            f.write_text('x' * 100, encoding='utf-8')
            os.utime(f, (old + i, old + i))   # 越靠后越新
        saved_root = cl.ROOT
        cl.ROOT = Path(d)
        try:
            items = cl.collect_logs(keep=2, keep_days=3)
            names = sorted(p.name for p, _k in items)
            check(names == ['run_0.log', 'run_1.log', 'run_2.log'],
                  '日志保留最近 2 个 → 其余 3 个待删')
            items2 = cl.collect_logs(keep=2, keep_days=30)
            check(items2 == [], '保留天数放宽（30 天）→ 不删任何日志')
        finally:
            cl.ROOT = saved_root

    # 3) workflows 目录保留最近 N 个
    with tempfile.TemporaryDirectory() as d:
        wf = Path(d) / 'workflows'
        wf.mkdir(parents=True)
        for i in range(4):
            p = wf / ('h3_%d' % i)
            p.mkdir()
            os.utime(p, (time.time() - (10 - i) * 3600,) * 2)
        saved_root = cl.ROOT
        cl.ROOT = Path(d)
        try:
            items = cl.collect_workflows(keep=2)
            check(sorted(p.name for p, _k in items) == ['h3_0', 'h3_1'],
                  'workflows 保留最近 2 个 → 旧 2 个待删')
        finally:
            cl.ROOT = saved_root

    # 4) 体量格式化
    check(cl._human(1536) == '1.5KB' and cl._human(5 * 1024 ** 3) == '5.0GB', '可读体积格式化')

    print('ALL_OK' if ok else 'SOME_FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
