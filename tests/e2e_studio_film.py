#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/e2e_studio_film.py — L2 端到端：一句话 → 剧本 → 分镜 → 预检 → 指令 → 质检 → 生产包。

零算力、零联网、不需要任何 key（默认规则引擎档）。两个用法：

  1) 纯本地全链（默认）
     py -3 tests/e2e_studio_film.py --brief "最后一个人类关掉了城市最后一盏灯" --shots 3
     期望输出末行：STUDIO_E2E_OK

  2) 带假引擎（真出片链路的 L2；先起 mock_engine）
     py -3 tests/mock_engine.py --port 7999 --video studio/assets/01_direct_720p.mp4 &
     set ENGINE_BASE_URL=http://127.0.0.1:7999/v1/jobs
     set ENGINE_STATUS_URL=http://127.0.0.1:7999/v1/jobs
     py -3 tests/e2e_studio_film.py --run-plan
     期望：逐段 OK + out/accept.json

  --inject fail 会在第 2 段注入"台词被写进画面提示词"的经典错误，
  用来验证「Critic 判分 → 自动改写 → 重试通过」这条反馈闭环真的在跑。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.harness import brain as B      # noqa: E402
from studio.harness import kit as K        # noqa: E402
from studio.harness import roles as R      # noqa: E402
from studio.harness import state as S      # noqa: E402

FAIL_LINE = '我们还有十二分钟'


class InjectBrain(B.Brain):
    """假大脑：给出一份"看起来没问题、但把台词写进了画面提示词"的剧本。"""

    kind = 'llm'

    def available(self):
        return True

    def ask(self, role, system, user, *, schema=''):
        if role != 'scriptwriter':
            return None
        good = ('wide shot of a lighthouse keeper walking along a stormy pier, '
                'environment: cold grey sea and wet planks, single location, continuous '
                'lighting logic, lighting: overcast daylight with soft falloff, '
                'style: cinematic film still, mood: resolute, camera: slow tracking shot, '
                'audio: wind and waves, the character stays silent here: mouth closed, '
                'no speech')
        bad = ('medium shot of the keeper turning to the radio, the keeper says %s while the '
               'needle drops, camera: slow push in, lighting: warm lamp against blue night, '
               'audio: static hiss' % FAIL_LINE)
        return {
            'title': '十二分钟',
            'setting': 'a lighthouse on a storm coast, night falling',
            'style': 'cinematic',
            'characters': {'KEEPER': 'a weathered lighthouse keeper in his fifties, grey beard, '
                                     'oilskin coat, calm eyes'},
            'segments': [{'cast': ['KEEPER'], 'prompt': good},
                         {'cast': ['KEEPER'], 'prompt': bad},
                         {'cast': ['KEEPER'], 'prompt': good}],
            'lines': {'1': {'text': FAIL_LINE, 'speaker': 'KEEPER', 'voice': 'auto'}},
        }


def make_engine(**kw):
    """按环境变量/入参造一个引擎（没配就是 None = 仅生产计划档）。"""
    import os as _os
    from studio.harness.engine import Engine
    ov = {'ENGINE_BASE_URL': kw.get('base') or _os.environ.get('ENGINE_BASE_URL', ''),
          'ENGINE_STATUS_URL': kw.get('status') or _os.environ.get('ENGINE_STATUS_URL', ''),
          'ENGINE_API_KEY': kw.get('key') or _os.environ.get('ENGINE_API_KEY', '')}
    if not ov['ENGINE_BASE_URL']:
        return None
    return Engine.from_overrides(ov, poll=float(kw.get('poll') or 1.0),
                                 timeout=int(kw.get('timeout') or 120))


def run_e2e(brief: str, *, target_seconds: float = 30.0, cast_mode: str = 'solo',
            inject: str = '', kit_dir: str = '', run_plan: bool = False,
            use_engine: bool = False, engine=None, engine_limit: int = 0) -> dict:
    brain = InjectBrain() if inject == 'fail' else None
    eng = engine if engine is not None else (make_engine() if use_engine else None)
    st = R.run_harness(brief, target_seconds=target_seconds, cast_mode=cast_mode,
                       brain=brain, kit_builder=K.build_kit,
                       engine=eng, engine_limit=engine_limit)
    out = {'state': st.state, 'errors': st.errors, 'shots': len(st.shots),
           'retries': st.retries, 'roles': {k: v['status'] for k, v in st.roles.items()},
           'score': (st.critic or {}).get('score'), 'kit': st.kit.get('name'),
           'kit_bytes': st.kit.get('bytes'), 'mode': st.mode,
           'engine': (st.delivery or {}).get('engine') or {}}
    if kit_dir and st.kit_blob:
        out['kit_path'] = K.save_kit(st.kit_blob, kit_dir)
        out['plan'] = json.loads(st.kit_blob['files']['plan.json'])
        out['trace_steps'] = len(st.trace)
    if run_plan and out.get('kit_path'):
        d = str(Path(out['kit_path']).parent)
        p = subprocess.run([sys.executable, 'run_plan.py'], cwd=d, capture_output=True, text=True)
        out['run_plan_rc'] = p.returncode
        out['run_plan_tail'] = (p.stdout or '')[-1200:]
        acc = Path(d) / 'out' / 'accept.json'
        if acc.exists():
            out['accept'] = json.loads(acc.read_text(encoding='utf-8'))
    return out


def _print_report(rep: dict) -> None:
    print('=== L2 端到端（一句话 → 生产包） ===')
    print('状态机结束状态：%s' % rep['state'])
    print('分镜段数：%d ｜ 质检段均分：%s ｜ 改写重试：%d' % (rep['shots'], rep['score'], rep['retries']))
    print('角色状态：%s' % json.dumps(rep['roles'], ensure_ascii=False))
    if rep.get('kit'):
        print('生产包：%s（%s 字节）' % (rep['kit'], rep['kit_bytes']))
    if rep.get('plan'):
        print('分镜表：')
        for shot in rep['plan']['shots']:
            print('  [%02d] %3d 帧 / %5.2fs ｜ %s ｜ %s' % (
                shot['idx'], shot['frames'], shot['seconds'],
                ('台词：' + shot['line']['text']) if shot.get('line') else '静默',
                (shot['prompt'] or '')[:56]))
    eng = rep.get('engine') or {}
    if rep.get('mode') == 'engine':
        print('引擎：%s' % eng.get('summary'))
        for row in eng.get('rows') or []:
            print('  [%s] %s ｜ job=%s ｜ %ss ｜ %s' % (
                row.get('idx'), '成片' if row.get('ok') else '失败', row.get('job_id'),
                row.get('elapsed'), row.get('file') or row.get('error')))
    if rep.get('run_plan_rc') is not None:
        print('run_plan.py 退出码：%s' % rep['run_plan_rc'])
        print((rep.get('run_plan_tail') or '').strip()[-800:])
    if rep['errors']:
        print('错误：%s' % rep['errors'])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='创空间 L2 端到端（零算力）')
    ap.add_argument('--brief', default='地球上最后一个人每天按时出门，去按下整座城市的电源总开关')
    ap.add_argument('--seconds', type=float, default=30.0)
    ap.add_argument('--shots', type=int, default=0, help='仅提示：段数由时长档决定')
    ap.add_argument('--cast', default='solo', choices=['solo', 'duo'])
    ap.add_argument('--inject', default='', choices=['', 'fail'],
                    help='fail = 注入第 2 段台词写进画面提示词的错误，验证自动改写重试')
    ap.add_argument('--kit-dir', default='/tmp/studio_e2e')
    ap.add_argument('--engine', action='store_true',
                    help='用 Harness 自己的引擎适配层真出片（需要 ENGINE_* 环境变量）')
    ap.add_argument('--engine-limit', type=int, default=0, help='只跑前 N 段（省时间）')
    ap.add_argument('--run-plan', action='store_true',
                    help='用生产包里的 run_plan.py 真的跑一遍（需要 ENGINE_* 环境变量）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)

    rep = run_e2e(args.brief, target_seconds=args.seconds, cast_mode=args.cast,
                  inject=args.inject, kit_dir=args.kit_dir, run_plan=args.run_plan,
                  use_engine=args.engine, engine_limit=args.engine_limit)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        _print_report(rep)

    problems = []
    if rep['state'] not in (S.READY, S.DELIVER):
        problems.append('状态机没有走到 READY/DELIVER：%s %s' % (rep['state'], rep['errors']))
    if not rep['kit']:
        problems.append('没有生成生产包')
    if rep['shots'] < 3:
        problems.append('分镜段数 %d < 3' % rep['shots'])
    if any(v not in ('ok', 'warn') for v in rep['roles'].values()):
        problems.append('有角色没跑完：%s' % rep['roles'])
    if args.inject == 'fail':
        if rep['retries'] < 1:
            problems.append('注入了错误但没有触发自动改写重试（retries=0）')
        if rep['state'] == S.READY and rep['score'] and rep['score'] < 6:
            problems.append('改写后段均分仍然过低：%s' % rep['score'])
    if args.run_plan and rep.get('run_plan_rc') not in (0, 2):
        problems.append('run_plan.py 退出码异常：%s' % rep.get('run_plan_rc'))
    if not os.environ.get('ENGINE_BASE_URL') and (args.run_plan or args.engine):
        problems.append('--run-plan / --engine 需要 ENGINE_BASE_URL / ENGINE_STATUS_URL')
    if args.engine and rep.get('mode') != 'engine':
        problems.append('配了引擎但 MODE 不是 engine：%s' % rep.get('mode'))
    if args.engine:
        eng = rep.get('engine') or {}
        if not eng.get('done'):
            problems.append('引擎一段都没出片：%s' % eng.get('summary'))

    if problems:
        for p in problems:
            print('❌ %s' % p)
        print('STUDIO_E2E_FAIL')
        return 1
    print('STUDIO_E2E_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
