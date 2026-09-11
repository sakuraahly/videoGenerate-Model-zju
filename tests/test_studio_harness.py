#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_studio_harness.py — 多 Agent Harness 单测（零 key、不联网、不起 UI）。

覆盖 P0 的两条验收（book-20 §7）：
  ① 一句话进 → 看板出现剧本卡 + 分镜表 + 预检结果；
  ② 零 key 状态下分镜表"照做就能拍"（提示词 / 帧数秒数 / 是否说话+台词 / 锚点 / 参考图槽位 / 验收规则）。
外加状态机白名单、假完成拦截、Critic 判分与自动改写、生产包结构、run_plan.py 可编译。
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.harness import brain as B          # noqa: E402
from studio.harness import critic as C         # noqa: E402
from studio.harness import guards as G         # noqa: E402
from studio.harness import kit as K            # noqa: E402
from studio.harness import roles as R          # noqa: E402
from studio.harness import state as S          # noqa: E402
from studio.rules import frames as FR          # noqa: E402

BRIEF = '一个陪伴机器人，永远同意你说的一切'
NL = chr(10)


def _run(**kw):
    kw.setdefault('brief', BRIEF)
    kw.setdefault('target_seconds', 45)
    return R.run_harness(**kw)


# ── 状态机 ──────────────────────────────────────────────────────────────────
class TestState:
    def test_illegal_transition_raises(self):
        st = S.StoryState(brief='x')
        with pytest.raises(S.StateError):
            st.enter(S.CRITIC)

    def test_legal_path_ok(self):
        st = S.StoryState(brief='x')
        st.enter(S.STORY)
        st.enter(S.SHOTS)
        assert st.state == S.SHOTS
        assert S.can_go(S.SHOTS, S.PRELINT)
        assert not S.can_go(S.SHOTS, S.CRITIC)

    def test_blocked_from_critic_allowed(self):
        st = S.StoryState(brief='x')
        st.state = S.CRITIC
        st.block('测试')
        assert st.state == S.BLOCKED and st.errors

    def test_trace_and_progress(self):
        st = S.StoryState(brief='x')
        st.log('scriptwriter', 'write_script', detail='ok')
        assert st.trace[0].i == 1 and st.trace[0].role == 'scriptwriter'
        assert st.board()['trace'][0]['action'] == 'write_script'
        assert st.progress()['percent'] == 0

    def test_role_status_and_board_counts(self):
        st = S.StoryState(brief='x')
        st.role_status('critic', 'warn', summary='有问题')
        b = st.board()
        assert b['roles']['critic']['status'] == 'warn'
        assert b['counts']['shots'] == 0
        assert b['state_label'] == S.LABELS[S.IDLE]


# ── guards ──────────────────────────────────────────────────────────────────
class TestGuards:
    def test_normalize_lines_list_to_dict(self):
        story = G.normalize_story({'title': 't', 'characters': ['A'],
                                   'segments': [{'prompt': 'a wide shot of a robot walking'}],
                                   'lines': [{'text': '你好', 'speaker': 'A'}]})
        assert isinstance(story['lines'], dict) and story['lines']['0']['text'] == '你好'
        assert isinstance(story['characters'], dict) and 'A' in story['characters']

    def test_normalize_rejects_garbage(self):
        with pytest.raises(G.GuardError):
            G.normalize_story({'no_segments': True})
        with pytest.raises(G.GuardError):
            G.normalize_story(['not', 'a', 'dict'])

    def test_story_problems_flags_quote_and_text_instruction(self):
        story = G.normalize_story({
            'title': 't', 'characters': {'A': 'd'},
            'segments': [{'prompt': 'a robot says "hello" with a big subtitle on screen',
                          'cast': ['A']}],
        })
        probs = ' '.join(G.story_problems(story))
        assert '引号' in probs or '字幕' in probs

    def test_frames_grid(self):
        assert G.frames_valid(5) and G.frames_valid(141)
        assert not G.frames_valid(100)
        assert G.snap_frames(100) % 17 == 5 % 17
        frames, secs = G.snap_seconds(5.0)
        assert frames in set(FR.frame_grid()) and abs(secs - frames / 24.0) < 1e-6

    def test_min_frames_for_line_grows_with_text(self):
        short = G.min_frames_for_line('好')
        long_ = G.min_frames_for_line('这是一句很长很长的台词，需要更多时间才说得完。')
        assert long_ > short

    def test_verify_completion_catches_fake_done(self):
        st = S.StoryState(brief='x')
        st.state = S.DONE
        probs = G.verify_completion(st)
        assert probs, '空状态宣称完成必须被拦下'
        assert any('scriptwriter' in p or '没有剧本' in p for p in probs)

    def test_honest_claims(self):
        st = S.StoryState(brief='x')
        c = G.honest_claims(st)
        assert c['engine_configured'] is False and c['must_not_say']


# ── brain ───────────────────────────────────────────────────────────────────
class TestBrain:
    def test_make_brain_tiers(self):
        assert B.make_brain({}).kind == 'rule'
        assert B.make_brain({'llm_base': 'http://x/v1', 'llm_key': 'k'}).kind == 'llm'
        assert B.make_brain({'agent_url': 'http://a', 'agent_token': 't'}).kind == 'agent'

    def test_rule_brain_answers_none(self):
        assert B.RuleBrain().ask('scriptwriter', 's', 'u') is None
        assert B.RuleBrain().available() is False

    def test_extract_json_from_fence(self):
        text = '说明' + NL + '```json' + NL + '{"a": 1}' + NL + '```' + NL + '尾巴'
        assert B._extract_json(text) == {'a': 1}

    def test_extract_json_garbage(self):
        assert B._extract_json('完全不是 JSON') is None

    def test_llm_brain_unavailable_without_key(self):
        br = B.LLMBrain('http://127.0.0.1:1/v1', '', 'm')
        assert br.available() is False
        assert br.ask('x', 's', 'u') is None


class _FakeBrain(B.Brain):
    """假大脑：按角色返回预设 JSON（用来验"模型提案 → 规则评估 → 择优"）。"""

    kind = 'llm'

    def __init__(self, script=None, prompt=None):
        self.script = script
        self.prompt = prompt

    def available(self):
        return True

    def ask(self, role, system, user, *, schema=''):
        if role == 'scriptwriter':
            return self.script
        if role == 'director':
            return self.prompt
        return None


# ── 五角色 + 主循环 ─────────────────────────────────────────────────────────
class TestRoles:
    def test_zero_key_runs_end_to_end(self):
        st = _run()
        assert st.state == S.READY, st.errors
        assert st.brain_kind == 'rule'
        assert not st.errors
        for key in R.ROLE_KEYS:
            assert st.roles[key]['status'] in ('ok', 'warn'), key
        assert st.script and st.shots and st.directives and st.critic and st.delivery
        assert st.prelint['ok'] is True

    def test_board_has_script_shots_prelint(self):
        b = _run().board()
        assert b['cards']['script']['title']
        assert b['cards']['shots'] and b['cards']['prelint']['summary']
        assert b['counts']['segments'] == len(b['cards']['shots'])
        assert b['mode'] == 'plan'

    def test_every_shot_is_shootable_without_keys(self):
        """P0 验收②：每段都含提示词 / 帧数秒数 / 是否说话+台词 / 锚点 / 参考图槽位 / 验收规则。"""
        st = _run(anchor=True, assets_licensed=True)
        assert st.shots
        for shot in st.shots:
            assert shot['prompt'].strip(), shot['idx']
            assert shot['frames'] in set(FR.frame_grid())
            assert abs(shot['seconds'] - shot['frames'] / 24.0) < 0.01
            assert shot['resolution'] in FR.RESOLUTION_PRESETS
            assert shot['anchor'] is True
            assert shot['ref_slots'] and all(s['path'].startswith('refs/') for s in shot['ref_slots'])
            d = next(x for x in st.directives if x['idx'] == shot['idx'])
            assert len(d['accept']) >= 3 and d['command'].strip()
            assert d['request']['frames'] == shot['frames']
            if shot['line']:
                assert shot['line']['text'] and shot['line']['voice']
                assert shot['line']['text'] not in shot['prompt']
            else:
                assert shot['silent'] is True

    def test_prompt_never_contains_text_instruction(self):
        st = _run(style='documentary', cast_mode='duo', target_seconds=60)
        for shot in st.shots:
            low = shot['prompt'].lower()
            for banned in ('subtitle', 'caption', 'watermark', '字幕', '水印'):
                assert banned not in low, (shot['idx'], banned)

    def test_chinese_line_gets_chinese_voice(self):
        st = _run()
        for shot in st.shots:
            if shot['line']:
                assert shot['line']['voice'] in ('xiaoxiao', 'yunxi')

    def test_empty_brief_blocked(self):
        st = R.run_harness('', target_seconds=30)
        assert st.state == S.BLOCKED and st.errors

    def test_prelint_gate_blocks_bad_story(self, monkeypatch):
        bad = {'title': 'x', 'characters': {'A': 'd'}, 'segments': [
            {'prompt': 'a robot says "hello"', 'cast': ['B'], 'seconds': 5}], 'lines': {}}
        monkeypatch.setattr(R, '_rule_script', lambda st: dict(bad))
        st = _run()
        assert st.state == S.BLOCKED
        assert not st.directives

    def test_model_script_rejected_when_it_has_quotes(self):
        st = _run(brain=_FakeBrain(script={'title': 't', 'characters': {'A': 'd'},
                                          'segments': [{'prompt': 'a robot says "hi"',
                                                        'cast': ['A']}], 'lines': {}}))
        assert st.script['via'] == 'rule'
        assert any(s.action == 'model_draft_rejected' for s in st.trace)

    def test_model_proposal_is_scored_against_rule_version(self):
        rich = ('A weathered maintenance robot kneels beside a sleeping child in a dim workshop, '
                'environment: cluttered workbench with warm lamps, single location, continuous '
                'lighting logic, lighting: warm practical lamp with soft falloff, '
                'style: cinematic film still, shallow depth of field, camera: slow dolly in, '
                'audio: low room hum and a faint servo whine, no speech, mouth closed')
        st = _run(brain=_FakeBrain(prompt={'prompt': rich}))
        assert st.script['via'] == 'rule'          # 剧本仍由规则档出
        assert any(s.action == 'model_proposal_scored' for s in st.trace)
        assert st.directives and all(d['score'] > 0 for d in st.directives)

    def test_retry_is_bounded(self):
        st = _run(max_retry=1)
        assert int(st.critic.get('rounds') or 0) <= 1
        assert st.retries <= len(st.shots)

    def test_injected_bad_shot_triggers_bounded_retry(self):
        """L2 反馈闭环：第 2 段台词被写进画面提示词 → Critic 判错 → 自动改写 → 重试通过。"""
        sys.path.insert(0, str(ROOT / 'tests'))
        import e2e_studio_film as e2e
        rep = e2e.run_e2e('十二分钟', target_seconds=30.0, inject='fail')
        assert rep['state'] == S.READY, rep['errors']
        assert rep['retries'] >= 1, '注入了错误却没有触发自动改写重试'
        assert rep['score'] >= 6.0

    def test_plan_request_from_form(self):
        st = R.plan_request({'brief': 'x', 'target_seconds': '30', 'cast_mode': 'duo',
                             'anchor': True})
        assert st.target_seconds == 30.0 and st.cast_mode == 'duo' and st.anchor is True


# ── Critic ──────────────────────────────────────────────────────────────────
class TestCritic:
    def _shot(self, **kw):
        base = {'idx': 0, 'prompt': 'a robot walks through a corridor, camera: wide static, '
                                    'lighting: cold overhead light, audio: room tone, no speech',
                'frames': 141, 'seconds': 5.875, 'resolution': '480p', 'cast': [],
                'style': 'cinematic', 'anchor': False, 'silent': False}
        base.update(kw)
        return base

    def test_good_shot_scores_high(self):
        r = C.score_shot(self._shot(), {'characters': {}},
                         {'params': {'resolution': '480p'}, 'command': 'x', 'ref_slots': []})
        assert r['score'] >= 6.0 and r['pass'] is True

    def test_quote_and_text_instruction_are_errors(self):
        r = C.score_shot(self._shot(prompt='a robot says "hi" with a subtitle on screen'),
                         {'characters': {}}, {'params': {'resolution': '480p'}, 'command': 'x'})
        codes = {i['code'] for i in r['issues'] if i['level'] == 'error'}
        assert 'compliance' in codes and r['score'] < 9

    def test_off_grid_frames_flagged(self):
        r = C.score_shot(self._shot(frames=100, seconds=4.16), {'characters': {}},
                         {'params': {'resolution': '480p'}, 'command': 'x'})
        assert any(i['code'] == 'duration' and i['level'] == 'error' for i in r['issues'])

    def test_short_frames_for_line_flagged(self):
        shot = self._shot(frames=29, seconds=1.2,
                          line={'text': '这是一句相当长的台词，一秒钟根本说不完。', 'speaker': 'A'})
        r = C.score_shot(shot, {'characters': {'A': 'd'}},
                         {'params': {'resolution': '480p'}, 'command': 'x'})
        assert any('台词' in i['msg'] for i in r['issues'])

    def test_rewrite_removes_quotes_and_fixes_frames(self):
        shot = self._shot(prompt='a robot says "hi" then walks then stops then turns',
                          frames=100, seconds=4.16,
                          line={'text': '你好', 'speaker': 'A'}, cast=['A'])
        new, fixes = C.rewrite_shot(shot, {'characters': {'A': 'd'}})
        assert '"' not in new['prompt'] and new['frames'] in set(FR.frame_grid())
        assert fixes and new.get('rewritten') is True

    def test_rewrite_drops_unknown_cast(self):
        shot = self._shot(cast=['幽灵角色'], silent=True)
        new, fixes = C.rewrite_shot(shot, {'characters': {'A': 'd'}})
        assert new['cast'] == [] and fixes

    def test_hard_issue_vetoes_pass(self):
        """硬伤一票否决：分数够高也不算过（否则"台词进画面"会被放过）。"""
        shot = self._shot(prompt='a robot walks then turns, the robot says 我们还有十二分钟, '
                                 'camera: wide static, lighting: cold light, audio: room tone')
        r = C.score_shot(shot, {'characters': {}}, {'params': {'resolution': '480p'},
                                                    'command': 'x', 'ref_slots': []})
        assert r['errors'] >= 1 and r['pass'] is False

    def test_score_all_summary(self):
        rep = C.score_all([self._shot()], {'characters': {}})
        assert 'CRITIC:' in rep['summary'] and 0 <= rep['score'] <= 10


# ── 引擎适配层（P2：真出片） ────────────────────────────────────────────────
class _FakeEngine:
    """假引擎：不联网，只验 Harness 与引擎之间的契约（模式、回传、失败如实上报）。"""

    def __init__(self, fail_idx=(), sync=False):
        self.fail_idx = set(fail_idx)
        self.sync = sync

    def available(self):
        return True

    def describe(self):
        return '假引擎（测试用）'

    def summary(self, batch=None):
        out = {'configured': True, 'host': 'fake', 'available': True, 'describe': self.describe()}
        if batch:
            out.update({'done': batch['done'], 'failed': batch['failed'],
                        'summary': batch['summary'], 'rows': batch['rows']})
        return out

    def run(self, directive, *, on_event=None, fetch=True):
        """对齐真 Engine.run 的接口（Harness 是逐段调用它的）。"""
        idx = directive['idx']
        ok = idx not in self.fail_idx
        row = {'idx': idx, 'kind': directive['request']['kind'], 'ok': ok,
               'job_id': 'fake-%s' % idx, 'status': 'completed' if ok else 'failed',
               'video_url': 'http://127.0.0.1:1/v.mp4' if ok else '',
               'file': '/tmp/shot_%02d.mp4' % idx if ok else '',
               'error': '' if ok else '假引擎：故意失败', 'elapsed': 0.1}
        if on_event:
            on_event('done', row)
        return row


class TestEngine:
    def test_available_needs_submit_url_only(self):
        """只配提交地址也算可用（同步直返型引擎）；但**绝不读环境变量**充数。"""
        from studio.harness.engine import Engine
        assert Engine('', 'http://h/v1/jobs', '').available() is False
        assert Engine('http://h/v1/jobs', '', '').available() is True
        assert Engine.from_overrides({}).available() is False
        assert Engine.from_overrides({'ENGINE_BASE_URL': 'http://h/v1/jobs'}).available() is True

    def test_describe_is_honest_when_unconfigured(self):
        from studio.harness.engine import Engine
        assert '仅生产计划' in Engine('', '', '').describe()

    def test_submit_reports_http_error_without_raising(self):
        from studio.harness.engine import Engine
        import urllib.error
        eng = Engine('http://h/v1/jobs', 'http://h/v1/jobs', 'k')

        def boom(*a, **kw):
            raise urllib.error.HTTPError('http://h', 404, 'not found', {}, None)
        eng._post = boom
        r = eng.submit({'kind': 't2v'})
        assert r['ok'] is False and '404' in r['error']

    def test_query_rejects_bad_job_id(self):
        from studio.harness.engine import Engine
        eng = Engine('http://h/v1/jobs', 'http://h/v1/jobs')
        assert eng.query('../../etc/passwd')['ok'] is False

    def test_run_without_status_url_reports_honestly(self):
        from studio.harness.engine import Engine
        eng = Engine('http://h/v1/jobs', '', '')
        eng._post = lambda *a, **kw: {'job_id': 'j1'}
        r = eng.run({'idx': 0, 'request': {'kind': 't2v'}}, fetch=False)
        assert r['ok'] is False and 'ENGINE_STATUS_URL' in r['error']

    def test_run_sync_engine_returns_video(self):
        from studio.harness.engine import Engine
        eng = Engine('http://h/v1/jobs', 'http://h/v1/jobs')
        eng._post = lambda *a, **kw: {'video_url': 'http://h/v.mp4'}
        r = eng.run({'idx': 0, 'request': {'kind': 't2v'}}, fetch=False)
        assert r['ok'] is True and r['video_url'].endswith('v.mp4')

    def test_summary_never_leaks_key(self):
        from studio.harness.engine import Engine
        s = Engine('http://user:pw@h/v1/jobs', 'http://h/v1/jobs', 'SECRET').summary()
        assert 'SECRET' not in json.dumps(s) and 'pw' not in json.dumps(s)

    def test_harness_runs_with_engine_and_reports_delivery(self):
        st = _run(engine=_FakeEngine())
        assert st.mode == 'engine' and st.state == S.DELIVER
        eng = st.delivery['engine']
        assert eng['done'] == len(st.shots) and eng['failed'] == 0
        assert st.roles['editor']['status'] == 'ok'
        assert any(s.action == 'engine_shot' for s in st.trace)

    def test_harness_stays_in_plan_without_engine(self):
        st = _run()
        assert st.mode == 'plan' and st.state == S.READY

    def test_engine_failure_is_reported_not_hidden(self):
        st = _run(engine=_FakeEngine(fail_idx=(1,)))
        eng = st.delivery['engine']
        assert eng['failed'] == 1 and '失败' in eng['advice']
        assert st.state == S.DELIVER          # 失败段不阻断交付，但会被如实标注
        assert any(s.status == 'error' and s.action == 'engine_shot' for s in st.trace)


# ── 生产包 ──────────────────────────────────────────────────────────────────
class TestKit:
    def _st(self):
        return _run(kit_builder=K.build_kit)

    def test_kit_has_all_files(self):
        st = self._st()
        assert set(st.kit_blob['files']) == {'plan.json', 'jobs.jsonl', 'commands.md',
                                             'run_plan.py', 'accept.md', 'post.md',
                                             'film.srt', 'trace.json', 'README.md'}
        assert st.kit['summary'].startswith('生产包') and st.kit['bytes'] > 1000

    def test_zip_is_valid_and_plan_matches_shots(self):
        st = self._st()
        z = zipfile.ZipFile(io.BytesIO(st.kit_blob['zip_bytes']))
        assert z.testzip() is None
        plan = json.loads(z.read('plan.json').decode('utf-8'))
        assert len(plan['shots']) == len(st.shots)
        assert plan['fps'] == 24 and plan['total_frames'] == sum(s['frames'] for s in st.shots)
        for shot in plan['shots']:
            assert shot['prompt'] and shot['accept']

    def test_jobs_jsonl_is_one_line_per_shot(self):
        st = self._st()
        lines = [l for l in st.kit_blob['files']['jobs.jsonl'].splitlines() if l.strip()]
        assert len(lines) == len(st.shots)
        for line in lines:
            body = json.loads(line)
            assert body['frames'] in set(FR.frame_grid()) and body['prompt']

    def test_run_plan_py_compiles(self):
        import py_compile
        import tempfile
        st = self._st()
        src = st.kit_blob['files']['run_plan.py']
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'run_plan.py'
            p.write_text(src, encoding='utf-8')
            py_compile.compile(str(p), doraise=True)
        assert 'ENGINE_BASE_URL' in src and '--only' in src

    def test_accept_and_readme_talk_about_boundaries(self):
        st = self._st()
        assert '验收' in st.kit_blob['files']['accept.md']
        readme = st.kit_blob['files']['README.md']
        assert '不部署' in readme and 'run_plan.py' in readme

    def test_trace_json_has_five_roles(self):
        st = self._st()
        trace = json.loads(st.kit_blob['files']['trace.json'])
        assert set(trace['roles']) == set(R.ROLE_KEYS)
        assert len(trace['steps']) == len(st.trace) and trace['steps'][0]['action']

    def test_save_kit_writes_zip(self, tmp_path):
        st = self._st()
        path = K.save_kit(st.kit_blob, tmp_path)
        assert Path(path).exists() and Path(path).stat().st_size > 1000
        assert zipfile.ZipFile(path).namelist()[0] == 'plan.json'

    def test_zip_bytes_are_deterministic(self):
        files = {'plan.json': '{}', 'README.md': 'x'}
        assert K.make_zip(files) == K.make_zip(files)

    def test_kit_includes_post_instructions_and_srt(self):
        """P3：后期指令层（超分/音频/字幕）与字幕原文都在包里。"""
        st = self._st()
        post = st.kit_blob['files']['post.md']
        for kw in ('超分', '混音', '字幕', 'RealESRGAN', '空间内**不执行**'):
            assert kw in post, kw
        srt = st.kit_blob['files']['film.srt']
        lines = [s for s in st.shots if s['line']]
        if lines:
            assert lines[0]['line']['text'] in srt
            assert '-->' in srt

    def test_srt_timeline_matches_shot_lengths(self):
        st = self._st()
        from studio.rules import post as P
        shots = [{'idx': 0, 'seconds': 4.0, 'line': None},
                 {'idx': 1, 'seconds': 6.0, 'line': {'text': '你好', 'voice': 'xiaoxiao'}}]
        srt = P.srt_from_shots(shots)
        assert '00:00:04,000 --> ' in srt and '你好' in srt

    def test_upscale_plan_is_honest(self):
        from studio.rules import post as P
        p = P.upscale_plan('480p', mode='4x', source_size=(864, 480))
        assert p['target_size'] == (3456, 1920)
        assert '合成' in p['honest_note']
        assert P.upscale_plan('480p', mode='none')['scale'] == 1

    def test_board_kit_card_is_json_safe(self):
        st = self._st()
        json.dumps(st.board(), ensure_ascii=False)
        assert 'zip_bytes' not in st.kit
