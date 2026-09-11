"""studio.harness.critic - Critic 角色的规则轨质检（0-10 分 + 可自动执行的改写）。

为什么规则轨是主轨：质检发生在**提交之前**，一次判分成本 0 秒 0 算力，
却有 spark 上真机踩出来的判据背书（帧网格 / 台词铁律 / 中文被画进画面 / 唇动无声…）。
模型轨（VLM 看帧）标为可选，由执行方接入 —— 见 book-20 第 4.3 节。

对外两个入口：
  score_shot(shot, story, directive) -> {'idx','score','issues':[...],'pass':bool}
  rewrite_shot(shot, story, issues)  -> (新 shot, [改了什么...])   # 反馈闭环的"自动改写"
"""
from __future__ import annotations

import re

from ..rules import frames as _fr
from ..rules import prompts as _pr
from ..rules import templates as _tp

PASS_SCORE = 6.0

_QUOTE_CHARS = '\u201c\u201d"\u300c\u300d\u300e\u300f'
_QUOTE_RE = re.compile('[' + _QUOTE_CHARS + ']')
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_CAMERA_WORDS = ('camera', 'shot', 'close-up', 'wide', 'medium', 'aerial', 'tracking',
                 'dolly', 'pan', 'tilt', 'static', 'over-the-shoulder')
_MOTION_WORDS = ('moves', 'walks', 'turns', 'looks', 'reaches', 'stands', 'sits', 'opens',
                 'raises', 'steps', 'watches', 'holds')

WEIGHTS = {
    'prompt_sections': 2.0,   # 六段是否齐（主体/环境/光影/风格/运镜/音频）
    'compliance': 2.0,        # 铁律：不写文字指令 / 无引号 / 台词不进画面
    'duration': 2.0,          # 帧网格 + 台词时长匹配
    'consistency': 2.0,       # 角色锚点 / 风格锚点 / 场景连续
    'executability': 2.0,     # 可直接照做：参数齐、参考图槽位、单镜单动作
}


def _issue(code, level, msg, fix=''):
    return {'code': code, 'level': level, 'msg': msg, 'fix': fix}


def _text(v) -> str:
    return str(v or '').strip()


def score_shot(shot: dict, story: dict = None, directive: dict = None) -> dict:
    """单段规则轨判分（满分 10）。"""
    story = story or {}
    prompt = _text(shot.get('prompt'))
    issues = []
    got = {}

    # 1) 六段完整度
    sec = {'subject': bool(_text(shot.get('subject')) or prompt),
           'environment': bool(_text(shot.get('environment'))) or 'environment' in prompt.lower(),
           'light': bool(_text(shot.get('light'))) or 'light' in prompt.lower(),
           'style': bool(_text(shot.get('style'))) or 'style' in prompt.lower(),
           'camera': bool(_text(shot.get('camera'))) or any(w in prompt.lower() for w in _CAMERA_WORDS),
           'audio': bool(_text(shot.get('audio'))) or 'audio' in prompt.lower()}
    missing = [k for k, v in sec.items() if not v]
    got['prompt_sections'] = 1.0 - len(missing) / 6.0
    if missing:
        issues.append(_issue('prompt_sections', 'warn',
                             '提示词缺段：%s' % '/'.join(missing),
                             '补上缺失段（六段式：主体/环境/光影/风格/运镜/音频）'))

    # 2) 合规（铁律）
    bad = []
    if _pr.has_text_instruction(prompt):
        bad.append('正向提示词含"文字/字幕"类指令 → 会被模型画进画面')
    if _QUOTE_RE.search(prompt):
        bad.append('提示词里有引号（引号是模型画字幕的触发开关）')
    line = shot.get('line') or {}
    lt = _text(line.get('text'))
    if lt and lt in prompt:
        bad.append('台词原文被写进了画面提示词（台词只能进 lines/line）')
    if _CJK_RE.search(prompt):
        bad.append('提示词里有中文 → 中文指令文本会被画成乱码叠字')
    got['compliance'] = 0.0 if bad else 1.0
    for b in bad:
        issues.append(_issue('compliance', 'error', b, '去掉该条款（字幕压制写进负向提示词）'))

    # 3) 时长：帧网格 + 台词时长
    frames = shot.get('frames') or 0
    grid_ok = int(frames) in set(_fr.frame_grid())
    line_need = 0
    if lt:
        line_need = _fr.frames_of(_fr.estimate_speech_seconds(lt) * 1.2)
    dur_ok = grid_ok and (not line_need or int(frames) >= int(line_need))
    got['duration'] = 1.0 if dur_ok else (0.5 if grid_ok else 0.0)
    if not grid_ok:
        issues.append(_issue('duration', 'error', '帧数 %s 不在 5+17k 网格上（%d fps 硬约束）'
                             % (frames, _fr.FPS), '吸附到最近的合法帧数'))
    if line_need and int(frames) < int(line_need):
        issues.append(_issue('duration', 'error',
                             '台词 %d 字约需 %d 帧，本段只有 %d 帧 → 话说一半画面就结束'
                             % (len(lt), line_need, int(frames)),
                             '把本段抬到 %d 帧（%.2fs）' % (line_need, line_need / float(_fr.FPS))))
    if shot.get('silent') and not _tp.SILENCE_CLAUSE.split(':')[0] in prompt.lower() \
            and 'no speech' not in prompt.lower():
        issues.append(_issue('duration', 'warn', '静默镜没有显式声明不说话 → 模型会自己让人物开口（唇动无声）',
                             '在音频段补 the character stays silent here: mouth closed, no speech'))

    # 4) 一致性：角色锚点 / 风格锚点
    chars = story.get('characters') or {}
    unknown = [c for c in (shot.get('cast') or []) if str(c) not in chars]
    anchor_ok = bool(shot.get('anchor')) or not shot.get('cast')
    style_ok = bool(_text(shot.get('style')))
    got['consistency'] = 1.0
    if unknown:
        got['consistency'] -= 0.5
        issues.append(_issue('consistency', 'error', 'cast 里的 %s 不在角色卡中 → 人物形象卡注入失败，脸会漂'
                             % '/'.join(map(str, unknown)), '改用角色卡里的名字'))
    if not anchor_ok:
        got['consistency'] -= 0.3
        issues.append(_issue('consistency', 'warn', '有角色但没有一致性锚点', '打开锚点，跨镜头锁同一张脸'))
    if not style_ok:
        got['consistency'] -= 0.2
        issues.append(_issue('consistency', 'warn', '本段缺风格锚点', '把整片风格写进每段（同一句）'))
    got['consistency'] = max(0.0, got['consistency'])

    # 5) 可执行性
    got['executability'] = 1.0
    d = directive or {}
    params = d.get('params') or {}
    if not params.get('resolution'):
        got['executability'] -= 0.4
        issues.append(_issue('executability', 'warn', '缺分辨率参数', '按画幅给 480p/720p'))
    if not d.get('command'):
        got['executability'] -= 0.3
        issues.append(_issue('executability', 'warn', '缺命令行等价形式', '补 commands.md 条目'))
    if shot.get('cast') and not (d.get('ref_slots') or []):
        got['executability'] -= 0.3
        issues.append(_issue('executability', 'warn', '有角色但没留参考图槽位',
                             '为每个角色留一个参考图槽位（refs/<角色>.png）'))
    if len(prompt) < 80:
        got['executability'] -= 0.4
        issues.append(_issue('executability', 'warn', '提示词过短（%d 字符）' % len(prompt),
                             '补足环境与动作细节'))
    then_n = len(re.findall(r'\bthen\b', prompt, re.I)) + prompt.count('然后')
    if then_n >= 3:
        got['executability'] -= 0.4
        issues.append(_issue('executability', 'warn', '一个镜头堆了 %d 个连续动作' % then_n,
                             '拆成两段（单镜单动作）'))
    if not any(w in prompt.lower() for w in _MOTION_WORDS):
        got['executability'] -= 0.2
        issues.append(_issue('executability', 'warn', '没有明确动作 → 生成结果不可控',
                             '写一个具体动作（谁做了什么）'))
    got['executability'] = max(0.0, got['executability'])

    score = round(sum(WEIGHTS[k] * got[k] for k in WEIGHTS), 2)
    return {'idx': shot.get('idx'), 'score': score, 'pass': score >= PASS_SCORE,
            'detail': {k: round(v, 2) for k, v in got.items()}, 'issues': issues}


def score_all(shots: list, story: dict = None, directives: list = None) -> dict:
    """全片判分：逐段 + 总分 + 待改清单。"""
    directives = directives or []
    dmap = {d.get('idx'): d for d in directives}
    rows = [score_shot(s, story, dmap.get(s.get('idx'))) for s in shots or []]
    scores = [r['score'] for r in rows] or [0.0]
    errs = [i for r in rows for i in r['issues'] if i['level'] == 'error']
    return {
        'shots': rows,
        'score': round(sum(scores) / len(scores), 2),
        'min_score': min(scores),
        'ok': all(r['pass'] for r in rows) if rows else False,
        'errors': len(errs),
        'issues': sum(len(r['issues']) for r in rows),
        'summary': 'CRITIC: 段均 %.2f/10 ｜ 最低 %.2f ｜ 硬伤 %d ｜ 建议 %d'
                   % (sum(scores) / len(scores), min(scores), len(errs),
                      sum(len(r['issues']) for r in rows)),
    }


def rewrite_shot(shot: dict, story: dict = None, issues: list = None) -> tuple:
    """按判分结果自动改写（规则级、0 成本）；返回 (新 shot, [改动说明])。

    只做**确定性**的修复：删引号、剔违规条款、抬帧数、补静默声明、剔未知角色。
    需要创作的部分（换词、重写动作）交给大脑档，本函数不硬编。
    """
    story = story or {}
    out = dict(shot)
    fixes = []
    prompt = _text(out.get('prompt'))

    if _QUOTE_RE.search(prompt):
        prompt = _QUOTE_RE.sub('', prompt)
        prompt = re.sub(r'\s{2,}', ' ', prompt)
        fixes.append('去掉提示词里的引号（防模型画字幕）')
    if _pr.has_text_instruction(prompt):
        prompt = _pr.sanitize_positive(prompt)
        fixes.append('剔除违反铁律的"文字/字幕"条款')
    lt = _text((out.get('line') or {}).get('text'))
    if lt and lt in prompt:
        prompt = prompt.replace(lt, '').strip(' ,;')
        fixes.append('把台词原文从画面提示词里移出（只留 lines）')

    need = _fr.frames_of(_fr.estimate_speech_seconds(lt) * 1.2) if lt else 0
    frames = int(out.get('frames') or 0)
    target = max(frames, need)
    if target not in set(_fr.frame_grid()):
        grid = _fr.frame_grid()
        target = next((g for g in grid if g >= target), grid[-1])
    if target != frames:
        out['frames'] = target
        out['seconds'] = round(target / float(_fr.FPS), 4)
        fixes.append('帧数 %d → %d（对齐 5+17k 网格并让台词说得完）' % (frames, target))

    if out.get('silent') and 'no speech' not in prompt.lower():
        prompt = (prompt.rstrip(' ,') + ', ' + _tp.SILENCE_CLAUSE).strip(', ')
        fixes.append('补静默声明（防模型自己让人物开口）')

    chars = story.get('characters') or {}
    cast = [c for c in (out.get('cast') or []) if str(c) in chars] if chars else list(out.get('cast') or [])
    if cast != list(out.get('cast') or []):
        fixes.append('剔除角色卡里没有的角色：%s'
                     % '/'.join(str(c) for c in out.get('cast') or [] if c not in cast))
        out['cast'] = cast
        if not cast:
            out['line'] = None
            out['silent'] = False

    out['prompt'] = prompt
    if fixes:
        out['rewritten'] = True
    return out, fixes


__all__ = ['score_shot', 'score_all', 'rewrite_shot', 'PASS_SCORE', 'WEIGHTS']
