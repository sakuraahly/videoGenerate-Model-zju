#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_script_timeout.py — RunScript 动态计时映射单测。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.agent.script_timeout import script_timeout, _SCRIPT_TIMEOUT, _SCRIPT_TIMEOUTS  # noqa: E402


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL:', msg)
        else:
            print('ok:', msg)

    check(script_timeout('story_film.py') == 7200, 'story_film 7200（分钟级长任务）')
    check(script_timeout('film_series.py') == 5400, 'film_series 5400')
    check(script_timeout('lipsync_chain.py') == 1800, 'lipsync 1800')
    check(script_timeout('h3_submit.py') == 900, 'h3_submit 900')
    check(script_timeout('runs/h3/story_film.py') == 7200, '带目录前缀按尾名')
    check(script_timeout('unknown.py') == _SCRIPT_TIMEOUT, '未列出=默认 600')
    check(len(_SCRIPT_TIMEOUTS) >= 7, '映射覆盖长任务族')
    print('ALL_OK' if ok else 'SOME_FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
