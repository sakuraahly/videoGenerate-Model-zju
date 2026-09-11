"""studio.harness.guards - 真实性校验与假完成拦截。

Harness 最怕两件事，本模块各管一件：
  1. **大脑胡说**：访客接入的模型吐回来的"剧本 JSON"字段缺失 / 形状不对 / 台词写进画面提示词。
     → normalize_story() 先把形状掰正，story_problems() 再列硬伤，过不了就退回规则引擎。
  2. **假装跑完**：状态到了 DONE 但 trace 里缺角色、缺产物、或把"仅方案"说成"已出片"。
     → verify_completion() 列问题，honest_claims() 给出**该说 / 不该说**的话术边界。

原则：宁可少说，不可虚报。本模块纯标准库，可单测。
"""
from __future__ import annotations

import re

from ..rules import frames as _fr
from ..rules import lint as _lint
from ..rules import prompts as _pr
from ..rules import templates as _tp

ROLE_KEYS = ('scriptwriter', 'shotplanner', 'director', 'critic', 'editor')

_QUOTE_RE = re.compile(r'[\u201c\u201d"\u300c\u300d]')


class GuardError(ValueError):
    """校验不过（调用方应当降级到规则引擎或直接拦下，而不是继续往下拍）。"""


def require(cond, msg: str) -> None:
    if not cond:
        raise GuardError(msg)


def _as_text(v) -> str:
    if v is None:
        return ''
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return ' '.join(_as_text(x) for x in v).strip()
    if isinstance(v, dict):
        return ' '.join(_as_text(x) for x in v.values()).strip()
    return str(v).strip()


# ── 形状归一化：把"能用的部分"尽量救回来 ─────────────────────────────────────
def normalize_story(obj, *, brief: str = '', style: str = 'cinematic') -> dict:
    """大脑给的剧本 → 规范形状（characters/lines 转 dict，segments 补 idx/cast）。

    救不回来的（不是 dict、没有 segments）抛 GuardError，调用方退回规则引擎。
    """
    require(isinstance(obj, dict), '剧本必须是 JSON 对象')
    segs_in = obj.get('segments')
    require(isinstance(segs_in, list) and segs_in, '剧本必须含非空 segments 数组')

    chars_in = obj.get('characters') or {}
    chars = {}
    if isinstance(chars_in, dict):
        for k, v in chars_in.items():
            chars[str(k)] = _as_text(v) or str(k)
    elif isinstance(chars_in, list):
        for c in chars_in:
            if isinstance(c, dict):
                name = _as_text(c.get('name') or c.get('id') or c.get('角色'))
                if name:
                    chars[name] = _as_text(c.get('desc') or c.get('description') or c) or name
            elif _as_text(c):
                chars[_as_text(c)] = _as_text(c)

    segments = []
    for i, seg in enumerate(segs_in):
        seg = seg if isinstance(seg, dict) else {'prompt': _as_text(seg)}
        prompt = _as_text(seg.get('prompt') or seg.get('subject') or seg.get('description'))
        cast = seg.get('cast')
        if isinstance(cast, str):
            cast = [cast]
        cast = [str(c) for c in (cast or []) if _as_text(c)]
        line = seg.get('line') if isinstance(seg.get('line'), dict) else None
        if line:
            line = {'text': _as_text(line.get('text')),
                    'voice': _as_text(line.get('voice')) or 'auto',
                    'spoken': bool(line.get('spoken', True)),
                    'speaker': _as_text(line.get('speaker')) or (cast[0] if cast else '')}
            if not line['text']:
                line = None
        segments.append({
            'idx': i, 'beat': _as_text(seg.get('beat')) or 'beat%d' % (i + 1),
            'prompt': prompt, 'cast': cast, 'line': line,
            'seconds': seg.get('seconds'), 'frames': seg.get('frames'),
            'camera': _as_text(seg.get('camera')), 'light': _as_text(seg.get('light')),
            'environment': _as_text(seg.get('environment')),
            'style': _as_text(seg.get('style')), 'audio': _as_text(seg.get('audio')),
            'note': _as_text(seg.get('note')),
        })

    lines_in = obj.get('lines')
    lines = {}
    if isinstance(lines_in, dict):
        for k, v in lines_in.items():
            if isinstance(v, dict) and _as_text(v.get('text')):
                lines[str(k)] = v
    elif isinstance(lines_in, list):
        for i, v in enumerate(lines_in):
            if isinstance(v, dict) and _as_text(v.get('text')):
                key = str(v.get('idx', i))
                lines[key] = v
    if not lines:                      # 从段内 line 提升成 story.lines
        for seg in segments:
            if seg.get('line'):
                lines[str(seg['idx'])] = seg['line']

    story = dict(obj)
    story.update({'characters': chars, 'segments': segments, 'lines': lines,
                  'title': _as_text(obj.get('title')) or (_as_text(brief)[:24] or '未命名'),
                  'style': _as_text(obj.get('style')) or style})
    return story


def story_problems(story: dict) -> list:
    """硬伤清单（取 lint 的 error + 本条原创性/可执行性判据）；空列表 = 可往下拍。"""
    out = []
    rep = _lint.lint_story(story)
    out.extend(rep.get('errors') or [])
    for i, seg in enumerate(story.get('segments') or []):
        p = _as_text(seg.get('prompt'))
        if len(p) < 24:
            out.append('seg%d: 提示词太短（%d 字符）→ 信息不足，拍出来大概率不是你要的' % (i, len(p)))
        if _pr.has_text_instruction(p):
            out.append('seg%d: 正向提示词里有"文字/字幕"指令 → 会被画进画面' % i)
        if not (_as_text(seg.get('camera')) or 'camera' in p.lower()):
            out.append('seg%d: 缺运镜/景别描述（camera）' % i)
    for seg in story.get('segments') or []:
        if seg.get('line') and not _as_text(seg['line'].get('speaker')):
            out.append('seg%s: 台词缺 speaker' % seg.get('idx'))
    return out


# ── 帧网格：spark H3 的硬约束（5 + 17k @ 24fps） ───────────────────────────────
def frames_valid(frames) -> bool:
    try:
        n = int(frames)
    except (TypeError, ValueError):
        return False
    return n in set(_fr.frame_grid())


def snap_frames(frames) -> int:
    """任意帧数 → 最近的合法帧数（宁可长一点，也不能短到话说一半）。"""
    try:
        n = int(frames)
    except (TypeError, ValueError):
        n = _fr.FRAME_BASE
    grid = _fr.frame_grid()
    ok = [g for g in grid if g >= n]
    return ok[0] if ok else grid[-1]


def snap_seconds(seconds) -> tuple:
    """秒数 → (合法帧数, 对应的秒数)，两者严格自洽。"""
    try:
        f = snap_frames(_fr.frames_of(float(seconds)))
    except (TypeError, ValueError):
        f = _fr.FRAME_BASE
    return f, f / float(_fr.FPS)          # 精确值：秒数必须严格等于 帧数/fps，不做四舍五入


def min_frames_for_line(text: str, margin: float = 0.2) -> int:
    """一句台词至少要多少帧（含留白），不足则话说一半画面就结束。"""
    return snap_frames(_fr.frames_of(_fr.estimate_speech_seconds(_as_text(text)) * (1 + margin)))


# ── 假完成拦截 ───────────────────────────────────────────────────────────────
def verify_completion(state) -> list:
    """宣称"完成"时必须成立的证据清单；返回空列表才算真完成。"""
    problems = []
    trace = getattr(state, 'trace', []) or []
    roles = getattr(state, 'roles', {}) or {}
    for key in ROLE_KEYS:
        row = roles.get(key) or {}
        if row.get('status') in (None, 'pending', 'running'):
            problems.append('角色 %s 没有跑完（status=%s）' % (key, row.get('status')))
    if not getattr(state, 'script', None):
        problems.append('没有剧本产物（script 为空）')
    if not getattr(state, 'shots', None):
        problems.append('没有分镜产物（shots 为空）')
    if not getattr(state, 'directives', None):
        problems.append('没有生产指令（directives 为空）')
    if getattr(state, 'state', '') in ('DONE', 'DELIVER') and not trace:
        problems.append('状态是完成但 trace 为空 —— 无证据的完成')
    if getattr(state, 'errors', None):
        problems.append('仍有未处理的 error：%s' % '; '.join(state.errors[:3]))
    return problems


def honest_claims(state) -> dict:
    """话术边界：哪些话可以说，哪些会构成不实陈述。"""
    mode = getattr(state, 'mode', 'plan')
    engine = mode == 'engine'
    return {
        'may_say': (
            ['本片由 Harness 规划的 N 段分镜、按生产包执行产出']
            if not engine else
            ['分镜由 Harness 规划并质检通过', '成片由访客自行配置的引擎生成']
        ),
        'must_not_say': [
            '不要在创空间里跑了视频模型（空间零模型，这是红线）',
            '不要说成片是参赛方算力产出的（算力来自访客自带引擎）',
            '不要把"仅生产计划"说成"已出片"',
        ],
        'engine_configured': engine,
    }
