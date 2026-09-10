#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_studio_backend.py — 创空间前端后端抽象层单测（不联网）。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))

import backend as be  # noqa: E402


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL:', msg)
        else:
            print('ok:', msg)

    # 默认（无 REMOTE_API）= demo
    saved = {k: os.environ.pop(k, None) for k in ('STUDIO_BACKEND', 'REMOTE_API', 'STUDIO_TOKEN')}
    try:
        check(be.pick_backend().name == 'demo', '默认走 demo 后端（免费 CPU 档）')
        os.environ['REMOTE_API'] = 'http://127.0.0.1:9/v1'
        os.environ['STUDIO_TOKEN'] = 'x' * 16
        check(be.pick_backend().name == 'remote', '有 REMOTE_API+TOKEN → auto 选 remote')
        os.environ['STUDIO_BACKEND'] = 'demo'
        check(be.pick_backend().name == 'demo', '显式 STUDIO_BACKEND=demo 覆盖')
        os.environ['STUDIO_BACKEND'] = 'local'
        lb = be.pick_backend()
        check(lb.name == 'local', 'local 后端可选')
        try:
            lb.submit({})
            check(False, 'local 后端未启用应报错说明')
        except RuntimeError as e:
            check('GPU' in str(e) and 'REMOTE_API' in str(e), 'local 报错含 GPU/网关指引')

        d = be.DemoBackend()
        res = d.submit({'kind': 'talk', 'prompt': '天冷了', 'resolution': '480p',
                        'seconds': 3, 'voice': 'h3', 'subtitle': False})
        check(res['state'] == 'demo' and res['job_id'].startswith('demo-'), 'demo 提交返回演示任务')
        check(res['title'] == '说话镜头' and res['echo']['台词' if False else '字幕'] == '不烧录',
              'demo 规格卡字段正确（类型/字幕）')
        check('免费 CPU' in d.note or '演示模式' in d.note, 'demo 说明含模式提示')
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    print('ALL_OK' if ok else 'SOME_FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
