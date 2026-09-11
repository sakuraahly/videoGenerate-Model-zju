#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_studio_board_ui.py — 制片看板 UI 的纯函数单测（不起 gradio、不联网、不用 GPU）。

被测对象是 studio/app.py 里新增的模块级渲染函数（build_app 只把它们塞进组件，没有额外逻辑），
所以这里直接断言字符串，不需要启动 UI、不需要任何模型或算力。

覆盖（对应验收清单）：
  1) 空看板 / 坏看板不崩：board_html(None|{}|怪形状) 与 8 个分块渲染器
  2) 5 张角色分工卡都在（角色名 / 职责 / 输入→输出 / 状态 / 档位 / 耗时 / 产出摘要）
  3) 分镜表每段自足：帧数 · 秒数 · 是否说话+台词 · 锚点 · 参考图槽位 · 提示词 + ≥2 条验收规则
  4) 预检 errors 渲染成红色、warnings 黄色、通过时绿色
  5) 决策轨迹表行数 == len(trace)，一行对应一步
  6) 未配置 key 时显眼提示「规则引擎模式（零 key）」
  7) 连通性失败**分类**说明（401/403、404、超时、未填完）——opener 注入假实现，绝不联网
  8) HTML 转义（模型产出里的 <script> 不许原样进页面）
真实看板用 roles.run_harness('一个陪伴机器人，永远同意你说的一切', target_seconds=45) 生成；
大脑显式钉在 RuleBrain（零 key 档），免得环境变量里的 LLM_* 把测试带向网络。
"""
import copy
import io
import json
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                 # studio.harness / studio.rules
sys.path.insert(0, str(ROOT / 'studio'))      # app.py（与其它 studio 测试同一套路数）

import app as studio_app                                          # noqa: E402
from studio.harness import brain as harness_brain                 # noqa: E402
from studio.harness import roles as harness_roles                 # noqa: E402

BRIEF = '一个陪伴机器人，永远同意你说的一切'
PANELS = ('board_status_html', 'board_roles_html', 'board_script_html', 'board_shots_html',
          'board_prelint_html', 'board_critic_html', 'board_trace_html', 'board_delivery_html')


def _real_board() -> dict:
    """真跑一遍编排（规则引擎档，零 key、零算力、毫秒级）。"""
    st = harness_roles.run_harness(BRIEF, target_seconds=45, brain=harness_brain.RuleBrain())
    return st.board()


@pytest.fixture(scope='module')
def board() -> dict:
    return _real_board()


@pytest.fixture(autouse=True)
def _no_env_brain(monkeypatch):
    """测试**绝不联网**：把可能存在的 LLM_*/AGENT_URL 摘掉。

    否则 harness 的 make_brain() 会走环境变量档真发 HTTP（plan_board/board_stream 都会），
    单测就变成了联网测试 —— 这是本仓库最容易踩的坑。
    """
    for k in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL', 'AGENT_URL', 'AGENT_TOKEN',
              'ENGINE_BASE_URL', 'ENGINE_STATUS_URL', 'ENGINE_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    yield


# ── 假 HTTP：连通性测试的 opener 注入（测试绝不联网）──────────────────────────
class _Resp:
    def __init__(self, body: bytes = b'{}', status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener_ok(body: bytes = b'{"model": "deepseek-v4-pro"}'):
    return lambda req, timeout=None: _Resp(body)


def _opener_http(code: int, body: bytes = b'{"error": "bad key"}'):
    def _send(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, 'boom', {}, io.BytesIO(body))
    return _send


def _opener_boom(exc):
    def _send(req, timeout=None):
        raise exc
    return _send


# ── 1) 空值 / 坏形状不崩 ─────────────────────────────────────────────────────
@pytest.mark.parametrize('blank', [None, {}, [], 'board', 0])
def test_blank_board_renders_without_crash(blank):
    html = studio_app.board_html(blank)
    assert isinstance(html, str) and '生成方案' in html
    for name in PANELS:
        out = getattr(studio_app, name)(blank)
        assert isinstance(out, str) and out


def test_broken_board_shape_does_not_crash():
    """卡片/角色/轨迹被给成怪类型时也不能炸（外部模型产出的东西不可信）。"""
    junk = {'state': 'READY', 'roles': ['x'], 'cards': {'shots': 'not-a-list', 'script': 3,
                                                        'prelint': None, 'critic': [], 'delivery': 7},
            'trace': 'nope', 'progress': 5, 'counts': None, 'brief': {'a': 1}}
    html = studio_app.board_html(junk)
    assert isinstance(html, str) and html
    for name in PANELS:
        assert getattr(studio_app, name)(junk)


def test_empty_brief_board_is_renderable():
    """一句话为空：harness 会拦住（BLOCKED），页面必须照常渲染并说清原因。"""
    board = studio_app.plan_board({'brief': ''})
    html = studio_app.board_html(board)
    assert board['state'] in ('BLOCKED', 'ERROR')
    assert '被闸门拦住' in html
    assert '访客没有输入任何一句话' in html


# ── 2) 角色分工卡（多 Agent 分工 + 调度状态）─────────────────────────────────
def test_five_role_cards_all_present(board):
    html = studio_app.board_roles_html(board)
    for name, title in (('StoryWriter', '编剧'), ('ShotPlanner', '分镜'), ('Director', '导演'),
                        ('Critic', '质检'), ('Editor', '剪辑')):
        assert name in html and title in html
    for field in ('职责', '输入 → 输出', '档位', '耗时', '产出摘要'):
        assert field in html
    for key in harness_roles.ROLE_KEYS:
        assert board['roles'][key]['status'] == 'ok'
        assert board['roles'][key]['status'] in html          # 状态徽标带原始码
        assert board['roles'][key]['summary'][:20] in html     # 产出摘要
    assert html.count('flex:1 1 210px') == 5                   # 正好 5 张卡


def test_role_cards_render_even_without_run():
    """没跑过 harness 也要画出 5 张卡（分工是架构事实，不该"看不见 Agent"）。"""
    html = studio_app.board_roles_html({})
    assert html.count('flex:1 1 210px') == 5
    assert 'pending' in html and 'StoryWriter' in html


# ── 3) 分镜表：照做就能拍 ────────────────────────────────────────────────────
def test_shots_table_is_self_sufficient(board):
    html = studio_app.board_shots_html(board)
    shots = board['cards']['shots']
    assert shots, '测试样本必须真的产出分镜'
    assert html.count('data-shot=') == len(shots)
    for s in shots:
        assert '%d' % s['frames'] in html                      # 帧数
        assert ('%.2f' % s['seconds']) in html                 # 秒数
        assert s['prompt'][:40] in html                        # 提示词（折叠在 <details> 里）
        assert '展开提示词' in html and '<details>' in html
        if s['ref_slots']:
            assert s['ref_slots'][0]['path'] in html           # 参考图槽位
        if s['line']:
            assert s['line']['text'] in html                   # 说话段：台词原文
        rules = studio_app.shot_accept_rules(s, board['cards']['script'])
        assert len(rules) >= 2, rules                          # 验收规则 ≥2 条
    assert '网格' in html and '静默' in html and '说话' in html
    assert '帧数' in html and '秒数 / 画幅' in html


def test_shot_accept_rules_handle_junk():
    """验收规则对空段/怪段也要给够 2 条（不能因为数据缺就少一条判据）。"""
    for shot in ({}, None, {'frames': 'x', 'line': {'text': '你好'}, 'cast': ['P1']}):
        rules = studio_app.shot_accept_rules(shot, None)
        assert len(rules) >= 2 and all(isinstance(r, str) and r for r in rules)


# ── 4) 预检面板：红 / 黄 / 绿 ────────────────────────────────────────────────
def _board_with_prelint(errors, warnings, ok, grid_bad=None):
    return {'state': 'BLOCKED', 'state_label': '被闸门拦住（需改稿）', 'mode': 'plan',
            'mode_label': '仅生产计划（未接引擎）', 'brain': 'rule', 'brief': 'x',
            'progress': {'done': 0, 'total': 10, 'percent': 0, 'state': 'BLOCKED'},
            'roles': {}, 'counts': {}, 'trace': [], 'elapsed_ms': 1,
            'cards': {'prelint': {'ok': ok, 'errors': list(errors), 'warnings': list(warnings),
                                  'summary': 'LINT_SUMMARY: errors=%d warnings=%d'
                                             % (len(errors), len(warnings)),
                                  'grid_bad': list(grid_bad or []),
                                  'stats': {'segments': 3, 'seconds': 12.0, 'frames': 288,
                                            'lines': 1, 'cast_segments': 3}}}}


def test_prelint_errors_are_red_and_warnings_amber():
    html = studio_app.board_prelint_html(_board_with_prelint(['第 2 段帧数不在网格上'], ['台词偏长'], False,
                                                            grid_bad=[2]))
    assert 'data-precheck="fail"' in html
    assert '#842029' in html and '第 2 段帧数不在网格上' in html     # errors → 红
    assert '#664d03' in html and '台词偏长' in html                 # warnings → 黄
    assert '段 3' in html and '12.00s' in html                      # stats 渲染出来


def test_prelint_pass_is_green(board):
    html = studio_app.board_prelint_html(board)
    assert 'data-precheck="pass"' in html and '#0f5132' in html
    assert '预检通过' in html


# ── 5) 决策轨迹表 ────────────────────────────────────────────────────────────
def test_trace_rows_equal_trace_length(board):
    html = studio_app.board_trace_html(board)
    trace = board['trace']
    assert trace, '轨迹是"真跑过"的证据，不能为空'
    assert html.count('data-trace-i=') == len(trace)
    for t in trace:
        assert str(t['i']) in html and t['action'] in html and t['role'] in html
    assert '决策轨迹' in html and '状态机' in html and '耗时' in html
    assert studio_app.board_trace_html({'trace': []}).count('data-trace-i=') == 0


# ── 6) 未配置 key → 规则引擎模式（显眼提示）─────────────────────────────────
def test_notice_says_rule_engine_when_no_key():
    md = studio_app.config_notice_md({})
    assert '规则引擎' in md and '零 key' in md
    assert '生产包' in md and '未配置' in md
    assert 'sk-' not in md                                     # 绝不回显任何密钥


def test_notice_switches_when_key_filled():
    md = studio_app.config_notice_md(studio_app.cfg_of_form('https://api.deepseek.com/v1',
                                                            'deepseek-chat', 'sk-secret-123'))
    assert '已配置' in md and 'deepseek-chat' in md
    assert 'sk-secret-123' not in md                           # key 绝不进页面文案
    assert '零 key' not in md
    eng = studio_app.config_notice_md(studio_app.cfg_of_form('', '', '',
                                                             'https://engine.example.com/v1'))
    assert '出片' in eng and '已配置' in eng


def test_cfg_memory_is_session_scoped():
    """页面填的值只缓存在进程内存、只认自己的会话 id（不落盘、不串会话）。"""
    sid = studio_app.remember_cfg('', {'llm_key': 'sk-a', 'llm_base': 'https://a.example/v1'})
    assert sid and len(sid) == 16
    assert studio_app.recall_cfg(sid)['llm_key'] == 'sk-a'
    sid2 = studio_app.remember_cfg('', {'llm_key': 'sk-b'})
    assert sid2 != sid and studio_app.recall_cfg(sid2)['llm_key'] == 'sk-b'
    assert studio_app.recall_cfg(sid)['llm_key'] == 'sk-a'
    assert studio_app.recall_cfg('nope') == {}


# ── 7) 连通性：失败必须分类说明（opener 注入假实现，不联网）───────────────────
def test_llm_probe_requires_all_three_fields():
    res = studio_app.test_llm_connection('', '', '')
    assert res['ok'] is False and res['category'] == 'config'
    assert 'Base URL' in res['message'] and '规则引擎' in res['message']
    assert '❌ 失败' in studio_app.format_conn_result(res)


@pytest.mark.parametrize('code,category,needle', [
    (401, 'auth', 'key 不对'),
    (403, 'auth', 'key 不对'),
    (404, 'notfound', 'Base URL'),
    (429, 'rate', '限流'),
    (500, 'server', '服务端错误'),
])
def test_llm_probe_classifies_http_errors(code, category, needle):
    res = studio_app.test_llm_connection('https://api.example.com/v1', 'm', 'sk-secret-123',
                                         opener=_opener_http(code))
    assert res['ok'] is False and res['category'] == category and res['status'] == code
    assert needle in res['message']
    assert 'sk-secret-123' not in res['message']               # 报错文案不回显密钥
    assert '❌ 失败：HTTP %d' % code in studio_app.format_conn_result(res)


def test_llm_probe_classifies_timeout_and_network():
    timed = studio_app.test_llm_connection('https://api.example.com/v1', 'm', 'k',
                                           opener=_opener_boom(TimeoutError('timed out')))
    assert timed['category'] == 'timeout' and '超时' in timed['message']
    down = studio_app.test_llm_connection('https://api.example.com/v1', 'm', 'k',
                                          opener=_opener_boom(OSError('getaddrinfo failed')))
    assert down['category'] == 'network' and '连不上' in down['message']


def test_llm_probe_success_and_url_normalisation():
    res = studio_app.test_llm_connection('https://api.example.com/v1/', 'm', 'k', opener=_opener_ok())
    assert res['ok'] is True and '连接成功（模型 deepseek-v4-pro）' in res['message']
    assert studio_app._chat_url('https://a.example/v1') == 'https://a.example/v1/chat/completions'
    assert studio_app._chat_url('https://a.example/v1/') == 'https://a.example/v1/chat/completions'
    assert studio_app._chat_url('https://a.example/v1/chat/completions') == \
        'https://a.example/v1/chat/completions'                 # 写全了不重复补


def test_engine_probe_never_raises():
    assert studio_app.test_engine_connection('')['category'] == 'config'
    bad = studio_app.test_engine_connection('https://eng.example.com/v1', opener=_opener_http(404))
    assert bad['ok'] is False and 'ENGINE_BASE_URL' in bad['message']
    good = studio_app.test_engine_connection('https://eng.example.com/v1', 'https://eng.example.com/v1/jobs',
                                             opener=_opener_ok(b'{"ok": true}'))
    assert good['ok'] is True and '引擎可达' in good['message']
    odd = studio_app.test_engine_connection('https://eng.example.com/v1',
                                            opener=_opener_boom(RuntimeError('weird')))
    assert odd['ok'] is False and odd['category'] in ('network', 'timeout')
    assert '❌ 失败' in studio_app.format_conn_result(odd)


def test_provider_presets_fill_base_and_model():
    choices = studio_app.harness_provider_choices()
    assert len(choices) == 5 and any('DeepSeek' in c for c in choices)
    base, model = studio_app.preset_values(choices[1])
    assert base.startswith('https://') and model
    assert studio_app.preset_values('不存在的服务商') == ('', '')


# ── 8) 安全与边界 ────────────────────────────────────────────────────────────
def test_board_escapes_model_output(board):
    """看板是 HTML：模型产出的尖括号必须转义（否则就是一个注入口子）。"""
    evil = copy.deepcopy(board)
    evil['cards']['script']['title'] = '<script>alert(1)</script>'
    evil['cards']['script']['characters'] = {'<img src=x onerror=1>': '<b>坏角色</b>'}
    evil['cards']['shots'][0]['prompt'] = '<script>steal()</script>'
    html = studio_app.board_html(evil)
    assert '<script>' not in html and 'onerror=1>' not in html
    assert '&lt;script&gt;' in html and '&lt;img' in html


def test_delivery_panel_states_the_boundary(board):
    html = studio_app.board_delivery_html(board)
    assert 'AI 声明' in html and '交付清单' in html
    assert '边界提示' in html and studio_app.BOUNDARY_NOTE in html
    assert '不跑视频模型' in html and '红线' in html
    fake = studio_app.board_delivery_html({'cards': {'delivery': {
        'title': 'T', 'shots': 1, 'seconds': 2.0, 'frames': 48, 'talking_shots': 0,
        'resolution': '480p', 'ai_disclaimer': '本片由 AI 生成', 'credits_suggestion': '片尾加一行',
        'deliverables': ['plan.json'], 'claims': {'may_say': ['可以这样说'],
                                                    'must_not_say': ['不要说已出片']}}}})
    assert '不要说已出片' in fake and '可以这样说' in fake and studio_app.BOUNDARY_NOTE in fake


def test_capability_page_texts():
    b = studio_app.boundary_diagram_md()
    for needle in ('本空间', '契约', '访客自带', '不推理', '不连任何本机 GPU', 'jobs.jsonl'):
        assert needle in b
    m = studio_app.mode_explain_md()
    for needle in ('仅生产计划', '真出片', 'ENGINE_BASE_URL', '规则引擎'):
        assert needle in m


# ── 9) 编排入口端到端（仍然是纯函数层）──────────────────────────────────────
def test_plan_board_returns_full_renderable_board():
    board = studio_app.plan_board({'brief': BRIEF, 'style': 'cinematic', 'target_seconds': 45,
                                   'cast_mode': 'solo', 'resolution': '480p', 'anchor': True})
    assert board['state'] in ('READY', 'DONE')
    assert board['brain'] == 'rule'                            # 没填 key → 规则引擎档
    assert set(board['roles']) == set(harness_roles.ROLE_KEYS)
    assert board['cards']['shots'] and board['cards']['script'] and board['cards']['delivery']
    html = studio_app.board_html(board)
    for needle in ('角色分工', '剧本卡', '分镜表', '质检', '决策轨迹', '交付说明'):
        assert needle in html
    assert '零 key' in html                                    # 顶部状态条的大脑档位


def test_delivery_panel_lists_production_kit():
    """生产包（拿到就能跑）要摊开给评审看：文件名 + 体量，而不是一句"已生成"。

    这里走 plan_board（它接上 studio.harness.kit.build_kit）；直接调 run_harness 的
    fixture 不传 kit_builder，因此那一份看板的 kit 为空 —— 两种都要能渲染。
    """
    board = studio_app.plan_board({'brief': BRIEF, 'target_seconds': 45})
    kit = board['cards']['kit']
    assert kit and kit.get('files'), '真实看板必须带生产包（kit_builder 已接上）'
    html = studio_app.board_delivery_html(board)
    assert 'data-kit="1"' in html and '生产包' in html
    for name in ('plan.json', 'jobs.jsonl', 'commands.md', 'run_plan.py', 'accept.md',
                 'trace.json', 'README.md'):
        assert name in html
    assert str(kit.get('bytes')) in html
    assert studio_app.board_delivery_html({'cards': {'kit': {}}}) # 空包不崩


def test_plan_board_builds_kit_and_keeps_plan_mode():
    board = studio_app.plan_board({'brief': BRIEF, 'target_seconds': 20})
    assert board['mode'] == 'plan'                             # 默认零算力：不碰任何外部引擎
    assert board['cards']['kit']['files'].get('jobs.jsonl')    # 每段一行请求体
    assert board['cards']['delivery']['deliverables']
    assert board['roles']['editor']['status'] == 'ok'


def test_safe_kit_builder_never_breaks_the_board():
    """打包炸了不能带走整块看板：方案照出，轨迹里如实记一笔警告。"""
    def _boom(st):
        raise RuntimeError('zip broken')

    st = harness_roles.run_harness(BRIEF, target_seconds=20, brain=harness_brain.RuleBrain(),
                                   kit_builder=studio_app._safe_kit_builder(_boom))
    board = st.board()
    assert board['state'] == 'READY' and board['cards']['kit'] == {}
    assert any('生产包构建失败' in (t.get('detail') or '') for t in board['trace'])
    assert studio_app.board_html(board)


def test_notice_engine_wording_is_honest():
    """配了引擎要说明"点哪个按钮才会真出片"，不能含糊成"自动帮你出片"。"""
    md = studio_app.config_notice_md(studio_app.cfg_of_form('', '', '',
                                                            'https://engine.example.com/v1'))
    assert '出片' in md and '算力与费用在你那一侧' in md


def test_build_engine_needs_submit_url_only():
    """引擎构造：没填提交地址 = None（仅生产计划档）；填了就该是可用的 Engine。"""
    assert studio_app.build_engine({}) is None
    eng = studio_app.build_engine({'engine_base': 'https://engine.example.com/v1'})
    assert eng is not None and eng.available() is True and eng.status_url == ''


def test_board_stream_without_engine_does_not_pretend():
    """没配引擎时：照常出规划看板，但必须明说"本次只出生产计划"，不假装出片。"""
    out = list(studio_app.board_stream({'brief': BRIEF, 'target_seconds': 20}, cfg={}))
    assert out and isinstance(out[0][0], dict)
    assert any(x[2] and '还没有配置引擎' in x[2] for x in out)


def test_board_stream_with_engine_runs_segments():
    """配了引擎：走 ENGINE→DELIVER，逐段回传，看板里能看到引擎结果。"""
    class _Eng:
        def available(self):
            return True

        def describe(self):
            return '假引擎'

        def summary(self, batch=None):
            out = {'configured': True, 'host': 'fake', 'available': True}
            if batch:
                out.update(batch)
            return out

        def run(self, directive, *, on_event=None, fetch=True):
            row = {'idx': directive['idx'], 'kind': 't2v', 'ok': True, 'job_id': 'j',
                   'status': 'completed', 'video_url': 'http://h/v.mp4', 'file': '',
                   'error': '', 'elapsed': 0.0}
            if on_event:
                on_event('done', row)
            return row

    out = list(studio_app.board_stream({'brief': BRIEF, 'target_seconds': 20},
                                       cfg={'engine_base': 'https://engine.example.com/v1'},
                                       engine=_Eng()))
    boards = [x[0] for x in out if isinstance(x[0], dict)]
    assert boards
    last = boards[-1]
    assert last['mode'] == 'engine'
    assert last['cards']['delivery']['engine']['done'] == last['counts']['shots']


def test_board_stream_rebuilds_kit_with_engine_evidence():
    """出片后重打生产包：zip 里的 trace.json 必须含 engine 步骤与成片结果。

    否则「🚀 出片」之后下载到的 zip 只有规划证据，评审看不到"真的出过片"这一段。
    """
    class _Eng:
        def available(self):
            return True

        def describe(self):
            return '假引擎'

        def summary(self, batch=None):
            out = {'configured': True, 'host': 'fake', 'available': True}
            if batch:
                out.update(batch)
            return out

        def run(self, directive, *, on_event=None, fetch=True):
            row = {'idx': directive['idx'], 'kind': 't2v', 'ok': True, 'job_id': 'jj',
                   'status': 'completed', 'video_url': 'http://h/v.mp4', 'file': '',
                   'error': '', 'elapsed': 0.1}
            if on_event:
                on_event('done', row)
            return row

    hold = {}
    out = list(studio_app.board_stream({'brief': BRIEF, 'target_seconds': 20},
                                       cfg={'engine_base': 'https://e/v1'},
                                       engine=_Eng(), hold=hold))
    assert out[-1][0]['mode'] == 'engine'
    trace = json.loads(hold['kit_blob']['files']['trace.json'])
    actions = [s['action'] for s in trace['steps']]
    assert 'engine_shot' in actions and 'build_kit' in actions
    assert trace['mode'] == 'engine'


def test_delivery_panel_renders_engine_results():
    """真出片分支：成片 / 失败 / 为什么失败 / 续跑建议都要上页面（失败如实标注）。"""
    board = {'cards': {'delivery': {
        'title': 'T', 'ai_disclaimer': '本片由 AI 生成', 'deliverables': [],
        'claims': {'must_not_say': ['不要说已出片']},
        'engine': {'summary': '引擎出片：1/2 段成片', 'done': 1, 'failed': 1,
                   'advice': '第 2 段失败 → run_plan.py --only 2',
                   'rows': [{'idx': 0, 'kind': 't2v', 'ok': True, 'status': 'completed',
                             'elapsed': 42, 'file': 'out/shot_00.mp4'},
                            {'idx': 1, 'kind': 'talk', 'ok': False, 'status': 'failed',
                             'elapsed': 9, 'error': 'HTTP 500'}]}}}}
    html = studio_app.board_delivery_html(board)
    assert 'data-engine="1"' in html and 'run_plan.py --only 2' in html
    assert html.count('data-engine-shot=') == 2
    assert '已成片' in html and 'HTTP 500' in html


def test_plan_board_keeps_plan_mode_when_engine_unavailable():
    """默认按钮永远是零算力：引擎不可用时绝不走"真出片"分支（不偷偷调外部接口）。"""
    class _Eng:
        def available(self):
            return False

    board = studio_app.plan_board({'brief': BRIEF, 'target_seconds': 20}, engine=_Eng())
    assert board['mode'] == 'plan' and '仅生产计划' in board['mode_label']


def test_kit_summary_shape_and_download_note():
    """新摘要形状（files: {名: {chars, lines}}）要按"字符/行"渲染，旧形状（纯文本）也不能崩。"""
    board = studio_app.plan_board({'brief': BRIEF, 'target_seconds': 20})
    kit = board['cards']['kit']
    assert kit.get('bytes') and kit.get('summary') and kit.get('name')
    html = studio_app.board_delivery_html(board)
    assert '字符 / ' in html and 'data-kit="1"' in html
    for name in ('plan.json', 'jobs.jsonl', 'run_plan.py', 'accept.md', 'trace.json'):
        assert name in html
    legacy = studio_app.board_delivery_html({'cards': {'kit': {
        'name': 'old.zip', 'bytes': 10, 'files': {'x.md': 'hello\nworld'}}}})
    assert 'old.zip' in legacy and 'x.md' in legacy


def test_save_kit_blob_writes_a_real_zip(tmp_path):
    """下载按钮指向的就是这个文件：真的能落盘、真的是 zip、里面有生产包文件。"""
    out = studio_app.plan_board_full({'brief': BRIEF, 'target_seconds': 20})
    blob = out['kit_blob']
    assert blob.get('zip_bytes'), 'plan_board_full 必须把 zip 字节带出来（看板里只放摘要）'
    path = studio_app.save_kit_blob(blob, str(tmp_path))
    assert path and Path(path).is_file() and zipfile.is_zipfile(path)
    names = zipfile.ZipFile(path).namelist()
    for n in ('plan.json', 'jobs.jsonl', 'run_plan.py', 'accept.md', 'trace.json', 'README.md'):
        assert n in names
    assert studio_app.save_kit_blob({}, str(tmp_path)) == ''       # 空 blob 不写盘
    assert studio_app.save_kit_blob(None, str(tmp_path)) == ''
    assert Path(studio_app.kit_out_dir()).is_dir()                 # 默认目录存在（且在 allowed_paths 里）


def test_kit_note_md_reports_three_states():
    """下载提示三种状态都要如实说：生成了 / 落盘失败 / 本次没有。"""
    board = {'state_label': '方案就绪', 'cards': {'kit': {'name': 'k.zip', 'bytes': 1024,
                                                          'files': {'plan.json': {'chars': 1}}}}}
    ok = studio_app.kit_note_md(board, '/tmp/k.zip')
    assert '生产包已生成' in ok and 'k.zip' in ok and '下载生产包' in ok
    assert '落盘失败' in studio_app.kit_note_md(board, '')
    assert '本次没有生产包' in studio_app.kit_note_md({'state_label': '被闸门拦住'}, '')
    assert studio_app.kit_note_md(None, '')
    assert '还没有生产包' in studio_app.KIT_IDLE_MD


def test_board_stream_hands_back_kit_for_download(tmp_path):
    """出片流式回调也要能下载：board_stream(hold=...) 必须回填生产包全量字节。

    这里不配引擎（cfg 为空）→ 生成器只出规划看板就收工，因此**不会联网**。
    """
    hold = {}
    frames = list(studio_app.board_stream({'brief': BRIEF, 'target_seconds': 20}, cfg={}, hold=hold))
    assert frames, '至少要 yield 一版看板'
    assert isinstance(frames[0][0], dict) and hold.get('board')
    path = studio_app.save_kit_blob(hold.get('kit_blob') or {}, str(tmp_path))
    assert path and zipfile.is_zipfile(path)
    assert studio_app.board_html(hold.get('board'))


def test_plan_board_survives_broken_form():
    """表单给怪值也不能白屏（演示现场最怕的不是跑不通，是页面挂掉）。"""
    for form in ({'brief': BRIEF, 'target_seconds': 'abc'}, {'brief': None},
                 {'brief': BRIEF, 'style': 123, 'cast_mode': []}):
        board = studio_app.plan_board(form)
        assert isinstance(board, dict) and studio_app.board_html(board)
