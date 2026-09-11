#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio/selfcheck.py — 编排链自检（创空间"一键自检"按钮 / 命令行都能用）。

为什么需要它：空间是**免费 CPU 档**，评审点开就能用，不能出现"点了没反应"。
自检只做**零算力**的事：加载规则、跑一遍状态机、装一次生产包、看一眼有没有可选引擎。

  RULES:   lint / 帧网格 / 词库 / 角色提示 是否加载完整
  HARNESS: 状态机冒烟（一句话 → 生产包）是否通过
  KIT:     生产包结构与必需文件是否齐全（含 run_plan.py 能否编译）
  ENGINE:  是否有可选引擎（**未配置 = 正常，不是错误**）
  MODE:    plan（默认）/ engine（配置了引擎）

用法：
    py -3 studio/selfcheck.py                      # 报告 + 退出码
    py -3 studio/selfcheck.py --json               # 机器可读
    py -3 studio/selfcheck.py --engine-url http://host/v1 --engine-status http://host/v1/jobs
退出码：0 = 自检通过（MODE 无论 plan/engine 都算通过）；1 = 有硬错误。
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.harness import critic as _critic          # noqa: E402
from studio.harness import guards as _guards          # noqa: E402
from studio.harness import kit as _kit                # noqa: E402
from studio.harness import roles as _roles            # noqa: E402
from studio.harness import state as _state            # noqa: E402
from studio.rules import delivery as _delivery        # noqa: E402
from studio.rules import frames as _frames            # noqa: E402
from studio.rules import lint as _lint                # noqa: E402
from studio.rules import prompts as _prompts          # noqa: E402
from studio.rules import roles as _role_txt           # noqa: E402
from studio.rules import templates as _templates      # noqa: E402
from studio.rules import voice as _voice              # noqa: E402

SELFCHECK_BRIEF = '地球上最后一个人每天按时出门，去按下整座城市的电源总开关'


def _ok(cond, msg, hits=None):
    return {'ok': bool(cond), 'msg': msg, 'hits': list(hits or [])}


def check_rules() -> dict:
    """规则层：词库、帧网格、lint、角色提示是否都在位。"""
    items = []
    grid = _frames.frame_grid()
    items.append(_ok(len(grid) > 100 and all(f % 17 == 5 % 17 for f in grid),
                     '帧网格 %d 档，全部满足 5+17k @ %d fps' % (len(grid), _frames.FPS),
                     ['%d..%d' % (grid[0], grid[-1])]))
    items.append(_ok(len(_frames.RESOLUTION_PRESETS) >= 5,
                     '分辨率档位 %s' % '/'.join(sorted(_frames.RESOLUTION_PRESETS))))
    combos = _templates.combo_count()
    items.append(_ok(combos >= 50, '分镜模板骨架 %d 套（要求 ≥50）' % combos))
    items.append(_ok(len(_voice.VOICES) >= 4, '音色表 %s' % '/'.join(_voice.VOICES)))
    items.append(_ok(len(_role_txt.ROLE_ORDER) == 5 and
                     all(_role_txt.system_for(k) for k in _role_txt.ROLE_ORDER),
                     '角色提示文本 5 份齐备'))
    rep = _lint.lint_story({'title': 't', 'characters': {'A': 'd'},
                            'segments': [{'prompt': 'a robot walks down a corridor at dawn',
                                          'cast': ['A'], 'seconds': 5}],
                            'lines': {}})
    items.append(_ok(isinstance(rep.get('errors'), list) and 'ok' in rep,
                     'lint 可调用（%s）' % rep.get('summary')))
    bad = _lint.lint_story({'title': 't', 'segments': [{'prompt': 'the sign says "STAR WARS"'}],
                            'lines': {}})
    items.append(_ok(bad['ok'] is False, 'lint 能拦住引号 + 版权词（负向用例）',
                     bad['errors'][:2]))
    pos = _prompts.build_prompt('a robot walks through a corridor, camera: wide static, '
                                'with subtitles burned in')
    items.append(_ok(not _prompts.has_text_instruction(pos),
                     '提示词组装会剔掉"字幕"类条款（铁律）'))
    return {'title': 'RULES 规则引擎', 'ok': all(i['ok'] for i in items), 'items': items}


def check_harness() -> dict:
    """编排层：状态机冒烟 + 白名单 + 五角色是否都跑到。"""
    items = []
    st = _roles.run_harness(SELFCHECK_BRIEF, target_seconds=30, kit_builder=_kit.build_kit)
    items.append(_ok(st.state == _state.READY, '状态机跑完一句话 → %s' % st.state,
                     st.errors[:3]))
    items.append(_ok(not st.errors, '无未处理错误'))
    missing = [k for k in _roles.ROLE_KEYS if (st.roles.get(k) or {}).get('status')
               not in ('ok', 'warn')]
    items.append(_ok(not missing, '五个角色都产出（缺：%s）' % (missing or '无')))
    items.append(_ok(len(st.trace) >= 10, 'trace %d 步（可导出）' % len(st.trace)))
    items.append(_ok(bool(st.shots) and all(s['frames'] in set(_frames.frame_grid())
                                            for s in st.shots),
                     '%d 段全部落在帧网格上' % len(st.shots)))
    items.append(_ok(bool(st.critic.get('shots')), '质检规则轨有判分（%s）'
                     % (st.critic.get('summary') or '')))
    illegal = False
    try:
        probe = _state.StoryState(brief='x')
        probe.enter(_state.CRITIC)
    except _state.StateError:
        illegal = True
    items.append(_ok(illegal, '非法状态跳转会被拦下（白名单生效）'))
    fake = _state.StoryState(brief='x')
    fake.state = _state.DONE
    items.append(_ok(bool(_guards.verify_completion(fake)), '假完成会被拦下（无证据的 DONE）'))
    return {'title': 'HARNESS 编排链', 'ok': all(i['ok'] for i in items), 'items': items,
            'state': st}


def check_kit(st) -> dict:
    """生产包：文件齐、zip 能开、run_plan.py 能编译、内容与分镜一致。"""
    items = []
    if st is None or not st.kit_blob:
        return {'title': 'KIT 生产包', 'ok': False,
                'items': [_ok(False, '没有拿到生产包（HARNESS 步骤失败）')]}
    files = st.kit_blob.get('files') or {}
    need = set(_kit.ORDER)
    items.append(_ok(need <= set(files), '必需文件齐全：%s' % '/'.join(_kit.ORDER),
                     sorted(set(files) - need)))
    try:
        z = zipfile.ZipFile(io.BytesIO(st.kit_blob['zip_bytes']))
        items.append(_ok(z.testzip() is None and set(need) <= set(z.namelist()),
                         'zip 可打开且文件齐（%.1f KB）' % (len(st.kit_blob['zip_bytes']) / 1024.0)))
        plan = json.loads(z.read('plan.json').decode('utf-8'))
        items.append(_ok(len(plan['shots']) == len(st.shots),
                         'plan.json 段数与分镜一致（%d 段）' % len(plan['shots'])))
        jobs = [l for l in z.read('jobs.jsonl').decode('utf-8').splitlines() if l.strip()]
        items.append(_ok(len(jobs) == len(st.shots), 'jobs.jsonl 每段一行（%d 行）' % len(jobs)))
        try:
            compile(z.read('run_plan.py').decode('utf-8'), 'run_plan.py', 'exec')
            items.append(_ok(True, 'run_plan.py 可编译'))
        except SyntaxError as e:
            items.append(_ok(False, 'run_plan.py 语法错误：%s' % e))
        items.append(_ok('AI 生成' in z.read('README.md').decode('utf-8'),
                         'README 含 AI 生成与边界说明'))
    except (zipfile.BadZipFile, ValueError, KeyError) as e:
        items.append(_ok(False, 'zip 读取失败：%s' % e))
    items.append(_ok(bool(_delivery.AI_DISCLAIMER) and bool(_delivery.VLM_CHECKLIST),
                     '交付规范（AI 声明 / 引擎侧检查项）在位'))
    return {'title': 'KIT 生产包', 'ok': all(i['ok'] for i in items), 'items': items}


def probe_engine(base_url: str, status_url: str = '', api_key: str = '',
                 timeout: int = 8) -> dict:
    """看一眼引擎在不在（**只做连通性探测，绝不提交任务** —— 提交要花访客的钱）。

    探测方式：POST 一个明显不完整的请求体。引擎正常应答"参数不全/400"也算**通了**；
    连不上/超时/404 才算不通。这样既验证了地址可达，又不会真的产生一条生成任务。
    """
    import urllib.error
    import urllib.request
    url = str(base_url or '').strip()
    if not url:
        return {'configured': False, 'reachable': False, 'detail': '未配置引擎（正常）'}
    req = urllib.request.Request(
        url, data=json.dumps({'kind': '__selfcheck__'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    if api_key:
        req.add_header('Authorization', 'Bearer ' + api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
            body = r.read(400).decode('utf-8', 'replace')
            return {'configured': True, 'reachable': True, 'status': r.status,
                    'detail': 'HTTP %s：%s' % (r.status, body[:120])}
    except urllib.error.HTTPError as e:
        detail = e.read(200).decode('utf-8', 'replace') if hasattr(e, 'read') else ''
        return {'configured': True, 'reachable': e.code not in (404, 502, 503, 504),
                'status': e.code, 'detail': 'HTTP %s：%s' % (e.code, detail[:120])}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'configured': True, 'reachable': False,
                'detail': '%s: %s' % (type(e).__name__, str(e)[:120])}


def check_engine(base_url: str = '', status_url: str = '', api_key: str = '') -> dict:
    items = []
    probe = probe_engine(base_url, status_url, api_key)
    if not probe['configured']:
        items.append(_ok(True, '未配置引擎 → MODE = plan（这是**正常档**，不是错误）'))
    else:
        items.append(_ok(probe['reachable'], '引擎连通性：%s' % probe['detail']))
        items.append(_ok(bool(status_url), '状态查询地址已配置（没配就只能从本会话记录看进度）'))
    return {'title': 'ENGINE 可选引擎', 'ok': all(i['ok'] for i in items), 'items': items,
            'probe': probe}


def run(engine_base: str = '', engine_status: str = '', engine_key: str = '') -> dict:
    """跑完整自检，返回报告（页面与 CLI 共用）。"""
    rules = check_rules()
    harness = check_harness()
    kit_rep = check_kit(harness.get('state'))
    engine = check_engine(engine_base, engine_status, engine_key)
    mode = 'engine' if engine['probe'].get('reachable') else 'plan'
    hard = [rules, harness, kit_rep]
    ok = all(s['ok'] for s in hard)
    return {
        'ok': ok,
        'mode': mode,
        'mode_label': ('真出片档（已配置可用引擎）' if mode == 'engine'
                       else '仅生产计划档（零 key、零算力，交付可执行生产包）'),
        'sections': {s['title']: {'ok': s['ok'], 'items': s['items']}
                     for s in (rules, harness, kit_rep, engine)},
        'summary': 'SELFCHECK: %s ｜ RULES %s ｜ HARNESS %s ｜ KIT %s ｜ ENGINE %s ｜ MODE %s'
                   % ('OK' if ok else 'FAIL',
                      *['OK' if s['ok'] else 'FAIL' for s in (rules, harness, kit_rep, engine)],
                      mode),
    }


def to_text(report: dict) -> str:
    lines = [report['summary'], '']
    for name, sec in report['sections'].items():
        lines.append('%s %s' % ('✅' if sec['ok'] else '❌', name))
        for item in sec['items']:
            mark = '  ✅' if item['ok'] else '  ❌'
            hits = ('  ← %s' % '; '.join(map(str, item['hits']))) if item.get('hits') else ''
            lines.append('%s %s%s' % (mark, item['msg'], hits))
        lines.append('')
    lines.append('MODE: %s' % report['mode_label'])
    return '\n'.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='创空间编排链自检（零算力）')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    ap.add_argument('--engine-url', default='', help='可选：视频生成引擎提交地址')
    ap.add_argument('--engine-status', default='', help='可选：引擎状态查询地址')
    ap.add_argument('--engine-key', default='', help='可选：引擎密钥（不会打印）')
    args = ap.parse_args(argv)
    report = run(args.engine_url, args.engine_status, args.engine_key)
    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != 'sections'} |
                         {'sections': report['sections']}, ensure_ascii=False, indent=2))
    else:
        print(to_text(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
