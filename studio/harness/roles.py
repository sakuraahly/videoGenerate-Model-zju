"""studio.harness.roles - 五个角色（谁干什么）+ 编排主循环 run_harness()。

角色分工（book-20 §4.1）：
  StoryWriter 编剧  一句话 → 剧本 JSON（片名/主题/角色卡/台词）
  ShotPlanner  分镜  剧本 → 分镜表（帧网格定时长 + 运镜/光影/一致性锚点）
  Director     导演  逐段生成完整生产指令（提示词/参数/请求体/命令行/参考图槽位）
  Critic       质检  规则轨 0-10 分 + 改进建议 + 自动改写重试（有界）
  Editor       剪辑  交付清单 + 生产包 + 轨迹导出

两种大脑共用同一条状态机：每个角色都先跑**规则实现**（零 key 也能演），
如果访客配了通用大模型，就再让模型提一版，**由 Critic 判分，谁分高用谁** ——
「模型提案 → 规则评估 → 择优采用」正是评分表里"评估中间结果"的实证。
"""
from __future__ import annotations

import hashlib
import json
import time

from ..rules import delivery as _dl
from ..rules import frames as _fr
from ..rules import lint as _lint
from ..rules import prompts as _pr
from ..rules import roles as _roles_txt
from ..rules import templates as _tp
from ..rules import voice as _voice
from . import critic as _critic
from . import guards as _g
from . import state as _st
from .brain import Brain, make_brain

MAX_LLM_SHOTS = 12          # 空间是免费 CPU 档：模型提案最多打几段的预算
DEFAULT_MAX_RETRY = 2       # 自动改写重试上限（有界，防死循环）

# 角色职责表与提示文本都是**纯文本**，放在 studio/rules/roles.py（可外置、可替换）
ROLES = [dict(key=k, **(_roles_txt.charter(k) or {})) for k in _roles_txt.ROLE_ORDER]
ROLE_KEYS = tuple(r['key'] for r in ROLES)

# 说明：角色提示文本与输出 schema 都在 studio/rules/roles.py（system_for / schema_for）


def _hash_seed(*parts) -> int:
    h = hashlib.sha256('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()
    return int(h[:8], 16) % 900000000 + 100000000


def _now_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _ask(st: _st.StoryState, brain: Brain, role: str, system: str, user: str,
         schema: str) -> dict:
    """问一次外置大脑；任何异常/不可用都返回 None（转规则档）。"""
    if brain is None or not brain.available():
        return None
    try:
        return brain.ask(role, system, user, schema=schema)
    except Exception:                                     # noqa: BLE001
        return None


# ══ 1) StoryWriter ═══════════════════════════════════════════════════════════
def _rule_script(st: _st.StoryState) -> dict:
    """规则档：模板库直出（6 母题 x 3 风格 x 3 时长 x 2 阵容 = 108 套骨架）。"""
    return _tp.build_storyboard(st.brief, style=st.style, target_seconds=st.target_seconds,
                                cast_mode=st.cast_mode, anchor=st.anchor, seed=st.seed,
                                assets_licensed=st.assets_licensed)


def run_storywriter(st: _st.StoryState, brain: Brain) -> dict:
    if st.state == _st.IDLE:
        st.enter(_st.STORY)
    t0 = time.perf_counter()
    st.role_status('scriptwriter', 'running')

    rule = _rule_script(st)
    story, via, note = rule, 'rule', '模板库直出（%s：%s）' % (rule.get('motif'), rule.get('motif_label'))

    schema = _roles_txt.schema_for('scriptwriter')
    user = ('访客的一句话：%s\n风格：%s\n目标时长：%s 秒\n阵容：%s\n锚点：%s\n\n%s'
            % (st.brief, st.style, st.target_seconds, st.cast_mode, st.anchor, schema))
    obj = _ask(st, brain, 'scriptwriter', _roles_txt.system_for('scriptwriter'), user, schema)
    if obj:
        try:
            cand = _g.normalize_story(obj, brief=st.brief, style=st.style)
            probs = _g.story_problems(cand)
            if probs:
                st.log('scriptwriter', 'model_draft_rejected', status='warn', via=brain.kind,
                       detail='模型剧本没过闸门（%d 条）→ 退回规则档：%s' % (len(probs), probs[0]),
                       data={'problems': probs[:8]})
            else:
                story, via, note = cand, brain.kind, '模型产出并通过规则闸门'
        except _g.GuardError as e:
            st.log('scriptwriter', 'model_draft_rejected', status='warn', via=brain.kind,
                   detail='模型剧本形状不可用（%s）→ 退回规则档' % e)

    story['source'] = ('规则引擎/模板库' if via == 'rule' else '外置大脑（访客自带模型）')
    story['via'] = via
    st.script = story
    st.role_status('scriptwriter', 'ok', via=via,
                   summary='《%s》%d 段 ｜ %s' % (story.get('title'), len(story.get('segments') or []), note),
                   ms=_now_ms(t0))
    st.log('scriptwriter', 'write_script', via=via, ms=_now_ms(t0),
           detail='《%s》%d 段 ｜ 主题 %s ｜ %s'
                  % (story.get('title'), len(story.get('segments') or []),
                     story.get('theme') or story.get('motif'), note),
           data={'title': story.get('title'), 'segments': len(story.get('segments') or []),
                 'characters': list((story.get('characters') or {}).keys())})
    return story


# ══ 2) ShotPlanner ═══════════════════════════════════════════════════════════
def _persona_voices(story: dict) -> dict:
    """每个角色固定一个音色（跨段不换嗓子），依据写进 reason 供人工复核。

    ⚠️ 语言以**台词原文**为准，角色卡描述只作性别线索 ——
    角色卡是英文的，若拿它选音色会给中文台词配出英文嗓子（spark 上踩过同款坑）。
    """
    lines = story.get('lines') or {}
    said = {}
    for v in (lines.values() if isinstance(lines, dict) else []):
        if isinstance(v, dict) and str(v.get('text') or '').strip():
            said.setdefault(str(v.get('speaker') or ''), []).append(str(v['text']))
    out = {}
    for name, desc in (story.get('characters') or {}).items():
        text = ' '.join(said.get(str(name)) or [])
        m = _voice.match_voice_to_text(text or str(desc), '')
        out[str(name)] = {'voice': m['voice'], 'speed': 0.95, 'tone': '',
                          'lang': m.get('lang'), 'reason': m.get('reason'),
                          'basis': ('按该角色台词的语言' if text else '按角色卡描述（该角色暂无台词）')}
    return out


def _ref_slots(cast, cards) -> list:
    return [{'slot': '<Picture %d>' % (i + 1), 'name': str(name),
             'path': 'refs/%s.png' % name, 'required': True,
             'desc': (cards or {}).get(str(name), '')} for i, name in enumerate(cast or [])]


def run_shotplanner(st: _st.StoryState, brain: Brain) -> list:
    if st.state == _st.STORY:
        st.enter(_st.SHOTS)
    t0 = time.perf_counter()
    st.role_status('shotplanner', 'running')

    story = st.script or {}
    cards = story.get('characters') or {}
    resolution = st.resolution or story.get('resolution') or '480p'
    if resolution not in _fr.RESOLUTION_PRESETS:
        resolution = '480p'
    personas = _persona_voices(story)
    lines = story.get('lines') or {}

    shots, snapped = [], 0
    for i, seg in enumerate(story.get('segments') or []):
        seg = seg if isinstance(seg, dict) else {}
        cast = [str(c) for c in (seg.get('cast') or [])]
        line = seg.get('line') or lines.get(str(i)) or None
        if isinstance(line, dict) and not line.get('text'):
            line = None
        if line:
            line = dict(line)
            spk = str(line.get('speaker') or (cast[0] if cast else ''))
            line['speaker'] = spk
            pv = personas.get(spk) or {}
            if not line.get('voice') or line.get('voice') == 'auto':
                m = _voice.match_voice_to_text(line.get('text') or '', '')
                voice = pv.get('voice')
                # 角色固定音色只在**语言一致**时沿用；否则以台词语言为准（中文台词必须中文嗓子）
                if not voice or _voice.VOICE_LANGS.get(voice) != m.get('lang'):
                    voice = m['voice']
                line['voice'] = voice
            line.setdefault('spoken', True)
            line.setdefault('tone', pv.get('tone') or '')

        subject = seg.get('subject') or seg.get('prompt') or ''
        prompt = _pr.build_prompt(subject, environment=seg.get('environment') or '',
                                  light=seg.get('light') or '', style=seg.get('style') or st.style,
                                  camera=seg.get('camera') or '', audio=seg.get('audio') or '')

        wanted = _fr.frames_of(float(seg.get('seconds') or (st.target_seconds / max(1, len(story.get('segments') or [1])))))
        need = _g.min_frames_for_line(line['text']) if line else 0
        frames = _g.snap_frames(max(wanted, need))
        if frames != int(seg.get('frames') or 0):
            snapped += 1
        shots.append({
            'idx': i, 'beat': seg.get('beat') or 'beat%d' % (i + 1), 'prompt': prompt,
            'subject': subject, 'environment': seg.get('environment') or '',
            'light': seg.get('light') or '', 'style': seg.get('style') or st.style,
            'camera': seg.get('camera') or '', 'audio': seg.get('audio') or '',
            'cast': cast, 'line': line, 'silent': bool(cast) and not line,
            'seconds': round(frames / float(_fr.FPS), 4), 'frames': frames,
            'resolution': resolution, 'anchor': bool(st.anchor or seg.get('anchor')),
            'ref_slots': _ref_slots(cast, cards),
            'seed': _hash_seed(st.seed, st.brief, i),
        })

    story['persona_voices'] = personas
    story['resolution'] = resolution
    st.shots = shots
    st.role_status('shotplanner', 'ok',
                   summary='%d 段 ｜ %s ｜ 总 %.1fs / %d 帧'
                           % (len(shots), resolution, sum(s['seconds'] for s in shots),
                              sum(s['frames'] for s in shots)),
                   ms=_now_ms(t0))
    st.log('shotplanner', 'plan_shots', ms=_now_ms(t0),
           detail='%d 段，帧网格校正 %d 段，台词段 %d 段'
                  % (len(shots), snapped, sum(1 for s in shots if s['line'])),
           data={'shots': [{'idx': s['idx'], 'frames': s['frames'], 'seconds': s['seconds'],
                            'talk': bool(s['line'])} for s in shots]})
    return shots


# ══ 3) 预检闸门（属于 Critic 的规则轨，但发生在花算力之前） ══════════════════
def run_prelint(st: _st.StoryState) -> dict:
    if st.state == _st.SHOTS:
        st.enter(_st.PRELINT)
    t0 = time.perf_counter()
    story = dict(st.script or {})
    story['segments'] = [dict(s) for s in st.shots]      # 让 lint 看到校正后的段
    rep = _lint.lint_story(story)
    grid_bad = [s['idx'] for s in st.shots if not _g.frames_valid(s['frames'])]
    rep['grid_bad'] = grid_bad
    rep['stats'] = {
        'segments': len(st.shots),
        'seconds': round(sum(s['seconds'] for s in st.shots), 2),
        'frames': sum(s['frames'] for s in st.shots),
        'lines': sum(1 for s in st.shots if s['line']),
        'cast_segments': sum(1 for s in st.shots if s['cast']),
    }
    st.prelint = rep
    status = 'ok' if rep['ok'] and not grid_bad else 'error'
    st.role_status('critic', 'ok' if rep['ok'] else 'error',
                   summary=rep['summary'] + (' ｜ 帧网格异常 %d 段' % len(grid_bad) if grid_bad else ''))
    st.log('critic', 'prelint', status=status, ms=_now_ms(t0),
           detail=rep['summary'] + (' ｜ 帧网格异常段 %s' % grid_bad if grid_bad else ''),
           data={'errors': rep['errors'][:8], 'warnings': rep['warnings'][:8],
                 'stats': rep['stats']})
    return rep


# ══ 4) Director ══════════════════════════════════════════════════════════════
def _seed_of(st: _st.StoryState, shot: dict) -> int:
    try:
        return int(str(st.seed)) if str(st.seed).strip().isdigit() else shot['seed']
    except (TypeError, ValueError):
        return shot['seed']


def _command_for(st: _st.StoryState, shot: dict) -> str:
    res = (shot.get('resolution') or '480p')
    sec = max(2, int(round(shot.get('seconds') or 5)))
    if shot.get('line'):
        return ('python3 runs/h3/talk_one.py --text "%s" --ref-image %s --audio-source h3 '
                '--resolution %s --seed %d --no-subtitle --out shot_%02d.mp4'
                % (shot['line']['text'], (shot['ref_slots'] or [{}])[0].get('path', 'refs/P1.png'),
                   res, _seed_of(st, shot), shot['idx']))
    return ('python3 runs/h3/generate.py --prompt-file prompts/shot_%02d.txt '
            '--resolution %s --seconds %d --seed %d --out shot_%02d.mp4'
            % (shot['idx'], res, sec, _seed_of(st, shot), shot['idx']))


def _directive(st: _st.StoryState, shot: dict, prompt: str, negative: str) -> dict:
    kind = 'talk' if shot.get('line') else 't2v'
    res = shot.get('resolution') or '480p'
    # frames 是**权威字段**（5+17k 网格硬约束）；seconds 只是给不认帧数的引擎的方便字段
    body = {'kind': kind, 'resolution': res,
            'seconds': round(float(shot.get('seconds') or 5), 2),
            'frames': shot.get('frames'), 'fps': _fr.FPS,
            'prompt': prompt, 'negative_prompt': negative, 'seed': _seed_of(st, shot)}
    if kind == 'talk':
        body['text'] = shot['line']['text']
        body['voice'] = shot['line'].get('voice') or 'native'
    return {
        'idx': shot['idx'], 'kind': kind, 'prompt': prompt, 'negative': negative,
        'params': {'resolution': res, 'frames': shot['frames'], 'seconds': shot['seconds'],
                   'fps': _fr.FPS, 'seed': body['seed'],
                   'lora': 'fl2v_4step' if kind == 't2v' else 'ref2v_8step'},
        'request': body,
        'command': _command_for(st, shot),
        'ref_slots': shot.get('ref_slots') or [],
        'line': shot.get('line'), 'cast': shot.get('cast') or [],
        'accept': _dl.accept_rules(shot['frames'], bool(shot.get('line')),
                                   (shot.get('line') or {}).get('text', ''), res),
        'notes': ['六段式正向提示词：主体/环境/光影/风格/运镜/音频',
                  '字幕与文字压制一律写在负向提示词，正向只字不提'],
    }


def run_director(st: _st.StoryState, brain: Brain) -> list:
    if st.state == _st.PRELINT:
        st.enter(_st.DIRECT)
    t0 = time.perf_counter()
    st.role_status('director', 'running')
    neg = _pr.negative_prompt()
    directives, upgraded = [], 0

    for shot in st.shots:
        base = _directive(st, shot, shot['prompt'], neg)
        base_score = _critic.score_shot(shot, st.script, base)['score']
        best, best_score, via = base, base_score, 'rule'

        if brain is not None and brain.available() and shot['idx'] < MAX_LLM_SHOTS:
            user = ('电影风格：%s\n本段任务：%s\n人物：%s\n是否说话：%s\n台词（若说话，不要写进画面提示词）：%s\n'
                    '导演给的基础提示词：%s\n\n%s'
                    % (st.style, shot['beat'], json.dumps(shot['cast'], ensure_ascii=False),
                       '说话' if shot['line'] else '不说话（必须显式声明静默）',
                       (shot['line'] or {}).get('text', ''),
                       shot['prompt'], _roles_txt.schema_for('director')))
            obj = _ask(st, brain, 'director', _roles_txt.system_for('director'), user,
                       _roles_txt.schema_for('director'))
            cand_text = str((obj or {}).get('prompt') or '').strip()
            if cand_text:
                cand_text = _pr.sanitize_positive(cand_text)
                if shot['line'] and shot['line']['text'] in cand_text:
                    cand_text = ''
            if cand_text:
                cand_neg = str((obj or {}).get('negative') or neg).strip() or neg
                cand = _directive(st, shot, cand_text, cand_neg)
                cand_score = _critic.score_shot(shot, st.script, cand)['score']
                st.log('director', 'model_proposal_scored', status='info', via=brain.kind,
                       detail='第 %d 段：模型提案 %.2f 分 vs 规则 %.2f 分 → %s'
                              % (shot['idx'], cand_score, base_score,
                                 '采用模型提案' if cand_score > base_score else '保留规则版'),
                       data={'model_score': cand_score, 'rule_score': base_score})
                if cand_score > base_score:
                    best, best_score, via = cand, cand_score, brain.kind
                    upgraded += 1

        best['score'] = best_score
        best['via'] = via
        directives.append(best)

    st.directives = directives
    st.role_status('director', 'ok',
                   summary='%d 段生产指令 ｜ 段均 %.2f 分%s'
                           % (len(directives), sum(d['score'] for d in directives) / max(1, len(directives)),
                              ' ｜ 采纳模型提案 %d 段' % upgraded if upgraded else ''),
                   ms=_now_ms(t0))
    st.log('director', 'direct', ms=_now_ms(t0),
           detail='%d 段生产指令（说话段 %d）｜ 采纳模型提案 %d 段'
                  % (len(directives), sum(1 for d in directives if d['kind'] == 'talk'), upgraded),
           data={'directives': [{'idx': d['idx'], 'kind': d['kind'], 'score': d['score'],
                                 'via': d['via'], 'frames': d['params']['frames']}
                                for d in directives]})
    return directives


# ══ 5) Critic：判分 + 自动改写重试 ═══════════════════════════════════════════
def run_critic(st: _st.StoryState, max_retry: int = DEFAULT_MAX_RETRY) -> dict:
    if st.state == _st.DIRECT:
        st.enter(_st.CRITIC)
    t0 = time.perf_counter()
    rep = _critic.score_all(st.shots, st.script, st.directives)
    attempt = 0
    while not rep['ok'] and attempt < max(0, int(max_retry)):
        attempt += 1
        changed = 0
        for row in rep['shots']:
            if row['pass']:
                continue
            idx = row['idx']
            shot = next((s for s in st.shots if s['idx'] == idx), None)
            if shot is None:
                continue
            new_shot, fixes = _critic.rewrite_shot(shot, st.script, row['issues'])
            if not fixes:
                continue
            pos = st.shots.index(shot)
            st.shots[pos] = new_shot
            d = next((x for x in st.directives if x['idx'] == idx), None)
            if d is not None:
                fresh = _directive(st, new_shot, new_shot['prompt'], d.get('negative') or '')
                fresh['via'] = d.get('via', 'rule')
                st.directives[st.directives.index(d)] = fresh
            changed += 1
            st.log('critic', 'rewrite', status='retry', detail='第 %d 段自动改写：%s'
                   % (idx, '；'.join(fixes)), data={'fixes': fixes, 'score': row['score']})
        rep = _critic.score_all(st.shots, st.script, st.directives)
        rep['rounds'] = attempt
        if not changed:
            break
    rep['rounds'] = rep.get('rounds', attempt)
    st.critic = rep
    st.role_status('critic', 'ok' if rep['ok'] else 'warn',
                   summary='%s ｜ 改写 %d 轮' % (rep['summary'], rep['rounds']))
    st.log('critic', 'quality_gate', status='ok' if rep['ok'] else 'warn', ms=_now_ms(t0),
           detail='%s ｜ 改写重试 %d 轮' % (rep['summary'], rep['rounds']),
           data={'score': rep['score'], 'min': rep['min_score'], 'errors': rep['errors'],
                 'rounds': rep['rounds']})
    if not rep['ok'] and not rep['rounds']:
        st.log('critic', 'quality_gate', status='warn',
               detail='仍有段未达标且无可自动修复项（需要大脑或人工改稿）')
    return rep


# ══ 6) Editor：交付说明（生产包在 kit.py，P1） ═══════════════════════════════
def run_editor(st: _st.StoryState, will_have_kit: bool = True) -> dict:
    t0 = time.perf_counter()
    st.role_status('editor', 'running')
    talk = [s for s in st.shots if s['line']]
    delivery = _dl.manifest((st.script or {}).get('title') or st.brief[:24],
                            shots=len(st.shots),
                            seconds=sum(s['seconds'] for s in st.shots),
                            frames=sum(s['frames'] for s in st.shots),
                            talking_shots=len(talk),
                            resolution=((st.shots[0] or {}).get('resolution') if st.shots
                                        else st.resolution),
                            has_kit=bool(will_have_kit))
    delivery['claims'] = _g.honest_claims(st)
    delivery['honest_notes'] = _dl.honest_notes(st.mode, bool(st.directives))
    st.delivery = delivery
    st.role_status('editor', 'ok', summary='交付清单 %d 项 ｜ %d 段 / %.1fs'
                   % (len(delivery['deliverables']), delivery['shots'], delivery['seconds']),
                   ms=_now_ms(t0))
    st.log('editor', 'delivery_manifest', ms=_now_ms(t0),
           detail='交付清单 %d 项，全片 %d 段 / %.1fs' % (len(delivery['deliverables']),
                                                         delivery['shots'], delivery['seconds']))
    return delivery


# ══ 编排主循环 ═══════════════════════════════════════════════════════════════
def run_harness(brief: str, *, style: str = 'cinematic', target_seconds: float = 30.0,
                cast_mode: str = 'solo', resolution: str = '', seed: str = '',
                anchor: bool = False, assets_licensed: bool = False,
                brain: Brain = None, max_retry: int = DEFAULT_MAX_RETRY,
                want_kit: bool = True, kit_builder=None) -> _st.StoryState:
    """一次「一句话出片」的完整编排；返回 StoryState（看板 / trace 都在里面）。

    零 key 也能跑完（规则引擎档）；接了大脑则每个角色都能被真模型扮演，Critic 判分择优。
    """
    brief = str(brief or '').strip()
    st = _st.StoryState(brief=brief, style=style, target_seconds=float(target_seconds or 30.0),
                        cast_mode=cast_mode, resolution=resolution, seed=str(seed or ''),
                        anchor=bool(anchor), assets_licensed=bool(assets_licensed))
    st.roles = {r['key']: {'status': 'pending', 'via': 'rule', 'summary': '', 'ms': 0,
                           'title': r['title'], 'name': r['name'], 'duty': r['duty'],
                           'inputs': r['inputs'], 'outputs': r['outputs']} for r in ROLES}
    brain = brain if brain is not None else make_brain()
    st.brain_kind = getattr(brain, 'kind', 'rule')
    st.log('orchestrator', 'start', status='info',
           detail='一句话：%s ｜ 大脑档位：%s' % (brief or '(空)', st.brain_kind))

    if not brief:
        st.block('访客没有输入任何一句话', 'orchestrator')
        return st

    try:
        run_storywriter(st, brain)
        run_shotplanner(st, brain)
        rep = run_prelint(st)
        if not rep['ok'] or rep.get('grid_bad'):
            st.block('预检未通过：%s' % '；'.join((rep['errors'] or ['帧网格异常'])[:3]), 'critic')
            return st
        run_director(st, brain)
        run_critic(st, max_retry=max_retry)

        st.enter(_st.KIT)
        t0 = time.perf_counter()
        st.role_status('editor', 'running')
        will_kit = bool(want_kit and kit_builder is not None)
        run_editor(st, will_have_kit=will_kit)

        st.mode = 'plan'
        st.enter(_st.READY)
        st.log('orchestrator', 'ready', status='info',
               detail='方案就绪（未接引擎）：%s' % ('生产包见下' if will_kit else '仅分镜与指令'))

        if will_kit:
            # 打包放在**最后**：trace.json 里必须是完整轨迹（含这一步本身），不能是残的
            step = st.log('editor', 'build_kit', detail='组装可执行生产包（%d 段）' % len(st.shots))
            step.ms = _now_ms(t0)
            full = kit_builder(st)
            st.kit_blob = full
            # 看板只放 JSON 安全的摘要（zip 字节不能进看板/JSON 组件）
            st.kit = full.get('summary') or {k: v for k, v in full.items()
                                             if k not in ('files', 'zip_bytes')}
            step.ms = _now_ms(t0)
            step.detail = '生产包已生成：%s' % (st.kit.get('summary') or '')
            step.data = {'files': list((full.get('files') or {}).keys()),
                         'bytes': st.kit.get('bytes'),
                         'zip': st.kit.get('name')}
            st.role_status('editor', 'ok',
                           summary='%s ｜ %s' % (st.roles['editor'].get('summary') or '',
                                                 st.kit.get('summary') or ''))
    except _st.StateError as e:
        st.log('orchestrator', 'state_error', status='error', detail=str(e))
    return st


def plan_request(form: dict = None, brain: Brain = None, **kw) -> _st.StoryState:
    """页面表单 → run_harness（app.py 只碰这一个函数）。"""
    form = dict(form or {})
    for k in ('brief', 'style', 'cast_mode', 'resolution', 'seed'):
        if form.get(k) is not None and k not in kw:
            kw[k] = form[k]
    for k in ('target_seconds',):
        if form.get(k) not in (None, '') and k not in kw:
            try:
                kw[k] = float(form[k])
            except (TypeError, ValueError):
                pass
    for k in ('anchor', 'assets_licensed', 'want_kit'):
        if k in form and k not in kw:
            kw[k] = bool(form[k])
    return run_harness(brain=brain, **kw)


__all__ = ['ROLES', 'ROLE_KEYS', 'run_harness', 'plan_request', 'run_storywriter',
           'run_shotplanner', 'run_prelint', 'run_director', 'run_critic', 'run_editor']
