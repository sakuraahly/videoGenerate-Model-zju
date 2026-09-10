#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_studio_agent_step.py — 创空间 Agent 一步逻辑单测（不联网，无 UI）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))

import app as studio_app  # noqa: E402


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print('FAIL:', msg)
        else:
            print('ok:', msg)

    # 空输入：不动历史、不给轨迹
    r = studio_app.agent_step('', [])
    check(r['history'] == [] and r['trace'] is None, '空输入不产生消息')

    # 说话镜头意图 → generate_talk（无 key 时走规则规划器，kind=demo）
    r = studio_app.agent_step('让参考图里的老人说一句“天冷了，快进屋坐坐吧。”', [])
    check(len(r['history']) == 2, '产生一轮 user+assistant')
    check('generate_talk' in (r['trace'] or ''), '轨迹里含 generate_talk 工具')
    check('规划结果' in r['history'][1]['content'] or '已提交' in r['history'][1]['content'],
          '助手消息含规划/提交说明')
    check(r['history'][1]['role'] == 'assistant', '消息角色正确')

    # 视频创意 → generate_video
    r2 = studio_app.agent_step('做一段雨夜老屋门口有猫的 5 秒镜头', [])
    check('generate_video' in (r2['trace'] or ''), '创意→generate_video')

    # 多轮：历史累积
    r3 = studio_app.agent_step('你们怎么做到不部署模型?', r2['history'])
    check(len(r3['history']) == 4, '多轮历史累积（4 条）')

    print('ALL_OK' if ok else 'SOME_FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
