#!/usr/bin/env python3
"""story_film — 剧本→分镜→台词→成片 一键主控（项目程序，agent run_script 可调）。

设计（2026-09-09 用户批评'重跑重头/剧情乱/人物混/超时中断'后的工程化答案）：
  1) 台词先行：台词表在剧本(story JSON)内预先定义（角色/文本/音色/发音写法 spoken），
     生成语音前已完成设置——**TTS 输入永远=台词表的 text（或 spoken 发音版）**，
     不允许模型现场编台词；
  2) 发音约束：合成后 ASR 回环校验 LINE_SCORE（阈值 0.70）；不达标且提供 spoken
     （读音写法）→ 自动用 spoken 重试一次；仍不达标→ 报告（不静默）；
  3) 断点续跑：进度 JSON（work-dir/state.json）逐段记录（段文件/末帧/台词文件）；
     重跑=自动 resume（跳过已完成段，从最后完成段的末帧继续 i2v）——重启/中断
     不再从 0 重来；--fresh 强制重来；
  4) 人物/剧情一致性：story JSON 的 characters 卡自动注入每段提示词（角色锚定句）
     + 延续句（同人物/同场景/同光照/慢速连续/无切）；剧本段次序=播放次序。

用法（spark）：
  python3 runs/h3/story_film.py --story config/story_oil_price.json \
      [--resolution 480p --seconds 4 --lora fl2v_4step --seed N --stitch --out x.mp4]
  python3 runs/h3/story_film.py --story config/story_oil_price.json --status   # 进度查询
story JSON：{title, style, characters:{NAME:desc}, segments:[{prompt, (line:{text,voice,spoken})}], ...}
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SUBMIT = PROJECT_ROOT / 'runs' / 'h3_submit.py'
LIPSYNC = PROJECT_ROOT / 'runs' / 'h3' / 'lipsync_chain.py'
STITCH = PROJECT_ROOT / 'runs' / 'h3' / 'film_stitch.py'
CONTINUE_TAIL = (' The shot continues seamlessly from the previous frame; same characters, '
                 'same location, same lighting, same color grade; slow continuous motion, no cuts. '
                 'Realistic physical logic: natural human movement, believable weight and gravity, '
                 'plausible camera. NO written characters, no signage text, no readable letters, '
                 'no numbers anywhere in frame; no text, no watermark, no cuts, no dialogue.')
LINE_SCORE_MIN = 0.70  # 发音回环阈值（台词 ASR 相似度）；低于则用 spoken 重试


def _run(cmd, timeout=7200):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _out_of(log: str) -> str:
    import re
    for pat in (r'LOCAL_OUTPUT: (outputs/\S+\.mp4)', r'REMOTE_VIDEO_PATH: (\S+\.mp4)'):
        m = re.search(pat, log)
        if m:
            v = m.group(1)
            if v.startswith('outputs/'):
                return str(PROJECT_ROOT / v)
            return str(Path.home() / 'ai' / 'ComfyUI' / 'output' / 'video' / Path(v).name)
    return ''


def _last_frame(video: Path, out_png: Path) -> bool:
    r = _run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-sseof', '-0.3', '-i', str(video),
              '-frames:v', '1', '-q:v', '2', str(out_png)])
    return r.returncode == 0 and out_png.is_file()


def _line_score_of(log: str) -> float:
    import re
    m = re.search(r'LINE_SCORE:\s*([0-9.]+)', log)
    return float(m.group(1)) if m else -1.0


def load_story(path: Path) -> dict:
    d = json.loads(path.read_text(encoding='utf-8'))
    if not d.get('segments'):
        raise ValueError('story 缺 segments')
    return d


def spoken_line_clause(line: dict, cast: list) -> str:
    """把台词原文写进提示词（2026-09-10 用户纠正：不要 TTS 配音盖掉 H3 原声）。

    实测：不写台词时 H3 会自己编造乱语人声（ASR 得到"哎让那警早牵传法案的亡吗"）；
    写进提示词后由 H3 自己说出该台词（talk_one 路线，ASR 可达 1.000），
    口型与语音本来就同步 → 成片=原生配音+字幕原文，不再"重新配音"。
    """
    text = str((line or {}).get('text') or '').strip()
    if not text:
        return ''
    spk = str((line or {}).get('speaker') or '').strip()
    if not spk and cast:
        spk = str(cast[0])
    who = spk or 'the character in frame'
    return ('SPOKEN LINE — %s speaks Mandarin Chinese, slowly and clearly, every syllable articulated, '
            'voice up-front and intelligible: "%s". The lip movement must match this speech exactly; '
            'no other speech, no mumbling, no overlapping voices.' % (who, text))


def build_prompt(seg: dict, story: dict, line: dict = None, voice_mode: str = 'native') -> str:
    """段提示词 = 作者 prompt + **故事背景** + 角色锚定句 + 在场约束 + 行为约束 + 风格句。

    剧本遵守（2026-09-09 用户批评'人物行为不按剧本/形象不符'后加）：
      · setting：故事背景句注入（年代/地域/种族适配，如 1940s America -> 欧美面孔）；
      · characters：角色形象卡（由故事内容设定，不再拍脑袋）；
      · cast：本镜头人物白名单（防多塞人/剧情溢出）；
      · 行为约束：只发生描述的动作，人物不提前进场/离场、无多余动作、无重复。
    """
    parts = []
    setting = str(story.get('setting') or '').strip()
    if setting:
        parts.append('Story setting: %s' % setting)
    parts.append(str(seg.get('prompt') or '').strip())
    chars = story.get('characters') or {}
    if chars:
        parts.append('Cast (identical in every shot): ' + '; '.join(
            '%s: %s' % (k, v) for k, v in chars.items()))
    cast = seg.get('cast')
    if cast is not None:  # 显式声明; 空列表=本镜头无人
        if cast:
            parts.append('Persons in this shot: %s only. '
                         'No other people anywhere in the frame.'
                         % ', '.join(str(c) for c in cast))
        else:
            parts.append('No people in this shot; empty scenery only.')
    if str(voice_mode) == 'native' and line:
        clause = spoken_line_clause(line, cast or [])
        if clause:
            parts.append(clause)
    parts.append('Only the described action happens in this shot; '
                 'characters do not enter, leave, appear or repeat actions '
                 'unless the prompt says so. The story order follows the '
                 'shot sequence exactly.')
    parts.append(str(story.get('style') or '').strip())
    return ' '.join(p for p in parts if p)


def state_path(work: Path) -> Path:
    return work / 'state.json'


def load_state(work: Path, story: dict) -> dict:
    p = state_path(work)
    if p.exists():
        try:
            st = json.loads(p.read_text(encoding='utf-8'))
            if st.get('title') == story.get('title'):
                return st
        except Exception:  # noqa: BLE001
            pass
    return {'title': story.get('title'), 'segments': {}, 'done': []}


def save_state(work: Path, st: dict) -> None:
    p = state_path(work)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')


def prompt_hash(prompt: str) -> str:
    """提示词指纹（md5 前 12 位）：story 文案变更→识别需重做。"""
    import hashlib
    return hashlib.md5(str(prompt).encode('utf-8')).hexdigest()[:12]


def seg_done(st: dict, idx: int) -> bool:
    s = st.get('segments', {}).get(str(idx))
    return bool(s and s.get('file') and Path(s['file']).is_file())


def seg_ready(st: dict, idx: int, prompt_ph: str, has_line: bool) -> bool:
    """断点就绪判定 = 文件存在 + 提示词指纹一致 + 台词段台词已完成。

    指纹不一致（剧本/形象/约束文案变更）→ 该段及**后续段**全部重做
    （i2v 首帧继承链不可保留断裂点）。
    """
    s = (st.get('segments') or {}).get(str(idx)) or {}
    if not (s.get('file') and Path(s['file']).is_file()):
        return False
    if s.get('ph') != prompt_ph:
        return False
    if has_line and not s.get('line'):
        return False
    return True


def syn_seg(st: dict, idx: int, seg: dict) -> None:
    """增量更新段状态（保留 ph 等既有键；台词链更新时不清画面指纹）。"""
    cur = st.setdefault('segments', {}).setdefault(str(idx), {})
    cur.update(seg)
    if idx not in st.setdefault('done', []):
        st['done'].append(idx)


def eff_seconds(audio_dur: float, base: int) -> int:
    """台词段视频秒数 = 台词音长 + 0.8s 余量（防'视频结束台词没说完'）；不足 base 用 base。"""
    import math
    d = float(audio_dur or 0)
    if d <= 0:
        return int(base)
    return max(int(base), int(math.ceil(d + 0.8)))


def instruct_text(line: dict) -> str:
    """台词个性=指令语气（CosyVoice2 instruct2）：line['tone'] 中文语气 → 指令文本。

    2026-09-10 实测事故：instruct2 在本机会卡死——子进程 100% CPU 空转 11 分钟、
    无输出无 wav（同一句不带 --instruct 时 13.4s 正常出音，rtf 0.93）。
    故默认关闭；确需启用时设环境变量 STORY_TTS_INSTRUCT=1。
    """
    import os as _os
    if _os.environ.get('STORY_TTS_INSTRUCT', '').strip().lower() not in ('1', 'true', 'on', 'yes'):
        return ''
    tone = str(line.get('tone') or '').strip()
    if not tone:
        return ''
    if not tone.endswith('地说'):
        tone = tone + '地说'
    return '用' + tone


def run_segment(idx: int, prompt: str, prev_frame, args, work: Path, st: dict,
                story: dict, sec: int | None = None) -> str:
    """生成一段；返回该段视频文件路径。sec=本段视频秒数（台词段按台词时长匹配）。"""
    cmd = ['python3', str(SUBMIT), '--stage', 'i2v' if prev_frame else 't2v',
           '--resolution', args.resolution, '--lora', args.lora,
           '--seconds', str(int(sec or args.seconds)), '--seed', str(args.seed),
           '--force-new']  # 故事片主控自带进度管理; 不用 h3_submit 的 last_job 断点
    if prev_frame:
        cmd += ['--image', str(prev_frame)]
    cmd += ['--prompt', prompt]
    print('== seg%d (%s)' % (idx, 'i2v' if prev_frame else 't2v'), flush=True)
    r = _run(cmd, timeout=int(args.timeout))
    log = (r.stdout or '') + (r.stderr or '')
    seg = _out_of(log)
    if not seg or not Path(seg).is_file():
        print('[错误] seg%d 产物未找到（rc=%s）' % (idx, r.returncode), file=sys.stderr)
        print(log[-600:], file=sys.stderr)
        raise RuntimeError('seg%d 生成失败' % idx)
    segp = Path(seg)
    lf = work / ('last_%d.png' % idx)
    if _last_frame(segp, lf):
        pass
    else:
        print('[warn] seg%d 末帧提取失败' % idx, file=sys.stderr)
    syn_seg(st, idx, {'file': str(segp), 'src_file': str(segp),
                      'prompt': prompt,
                      'ph': prompt_hash(prompt + '|sec=%d' % int(sec or args.seconds)),
                      'sec': int(sec or args.seconds)})
    save_state(work, st)
    print('seg%d OK: %s' % (idx, segp.name), flush=True)
    return str(segp)


def line_ph(line: dict) -> str:
    """台词指纹（文本+音色+语速+语气）：词表/个性变更→台词段重做（画面复用 src_file）。"""
    return prompt_hash('|'.join([str(line.get('text') or ''),
                                 str(line.get('voice') or 'yunxi'),
                                 str(line.get('speed') or 0.95),
                                 str(line.get('tone') or '')]))


ASR_PY = str(Path.home() / 'ai' / 'asr-venv' / 'bin' / 'python3')


def _asr_score(video: Path, start: float, dur: float, cmp_txt: str) -> float:
    """ASR 双窗验真（发音回环）：返回比例分；失败=-1。"""
    try:
        r = subprocess.run([ASR_PY, str(PROJECT_ROOT / 'runs' / 'h3' / 'asr_check.py'),
                            str(video), '--start', '%.3f' % start,
                            '--dur', '%.3f' % dur, '--compare', cmp_txt],
                           capture_output=True, text=True, timeout=600)
        import re as _re
        m = _re.search(r'^ASR_SCORE:\s*([\d.]+)$', (r.stdout or ''), _re.M)
        return float(m.group(1)) if m else -1.0
    except Exception:  # noqa: BLE001
        return -1.0


def run_line(idx: int, seg_file: str, line: dict, args, work: Path, st: dict) -> str:
    """台词处理（2026-09-09 重写：**无 W2L/GFPGAN 后期贴皮口型**）。

    = 台词先行（文本=台词表）→ CosyVoice2 合成（**人物个性=角色绑定音色+语速**）
      → 配音替换原轨 + 字幕=台词原文（**语言跟随台词**: 中文台词=中文字幕，
      英文台词=英文字幕）→ ASR 发音回环（失败自动 spoken 重试）。
    输出=画面原样+音轨+字幕（无后期口型驱动; 说话镜头如有需要可用 EchoMimic 原生驱动,另见 §15e）。
    """
    text = str(line.get('text') or '').strip()
    if not text:
        return seg_file
    spoken = str(line.get('spoken') or '').strip() or text
    voice = line.get('voice') or 'yunxi'
    speed = float(line.get('speed') or 0.95)
    out = work / ('seg_%02d_v.mp4' % idx)
    log = ''
    attempts = (text, spoken) if spoken != text else (text,)
    for attempt, use_text in enumerate(attempts):
        print('== seg%d 台词处理(t=%d) voice=%s speed=%.2f（无后期口型; 配音+字幕一次完成）'
              % (idx, attempt, voice, speed), flush=True)
        try:
            import sys as _sys
            if str(PROJECT_ROOT / 'runs') not in _sys.path:
                _sys.path.insert(0, str(PROJECT_ROOT / 'runs'))
            import h3.tts as _tts
            res = _tts.attach_speech_and_subtitle(
                Path(seg_file), use_text, out=out, voice=voice, backend='cosy',
                subtitle_style='harmony', subtitle_font='auto', subtitle_color='auto',
                audio_mode='replace', subtitle_source='text', narration='',
                speech_speed=speed, instruct=instruct_text(line))
            spd = float(res.get('speech_dur') or 0)
        except Exception as e:  # noqa: BLE001
            log = 'ERR %s' % e
            score = -1.0
            out.unlink(missing_ok=True)
            ok_file = False
        else:
            score = _asr_score(out, 0.0, spd + 0.30, use_text)
            ok_file = out.is_file() and out.stat().st_size > 0
        if ok_file and (attempt == 1 or score >= LINE_SCORE_MIN):
            if attempt == 1:
                print('seg%d 发音回环 FAIL(%.2f) → spoken 重试（台词文本不变, 发音写法替换）'
                      % (idx, score), flush=True)
            syn_seg(st, idx, {'file': str(out), 'line': text, 'voice': voice,
                              'speed': speed, 'score': score,
                              'spoken_used': attempt == 1,
                              'line_ph': line_ph(line)})
            save_state(work, st)
            print('seg%d 台词 %s ASR=%.2f (voice=%s speed=%.2f)'
                  % (idx, 'OK' if score >= LINE_SCORE_MIN else 'OK(spoken)', score,
                     voice, speed), flush=True)
            return str(out)
        if attempt == 0 and ok_file and score >= LINE_SCORE_MIN:
            syn_seg(st, idx, {'file': str(out), 'line': text, 'voice': voice,
                              'speed': speed, 'score': score, 'line_ph': line_ph(line)})
            save_state(work, st)
            return str(out)
    print('[错误] seg%d 台词处理最终失败（ASR=%.2f; %s）' % (idx, _line_score_of(log), log[-300:]),
          file=sys.stderr)
    return seg_file  # 兜底：保留源段（画面片）并报告


def run_line_native(idx: int, seg_file: str, line: dict, out: Path, work: Path, st: dict) -> str:
    """原生配音：台词已写进提示词→H3 自己说。这里只烧字幕 + ASR 回环验收（不替换音轨）。"""
    text = str((line or {}).get('text') or '').strip()
    if not text:
        return seg_file
    import sys as _s
    if str(PROJECT_ROOT / 'runs') not in _s.path:
        _s.path.insert(0, str(PROJECT_ROOT / 'runs'))
    import h3.tts as _tts
    try:
        res = _tts.attach_speech_and_subtitle(
            Path(seg_file), text, out=out, audio_mode='keep', subtitle_source='text',
            burn_subtitle=True, subtitle_style='harmony', subtitle_font='auto',
            subtitle_color='auto')
        spd = float(res.get('speech_dur') or 0)
    except Exception as e:  # noqa: BLE001
        print('[错误] seg%d 原生台词字幕失败: %s' % (idx, str(e)[:200]), file=sys.stderr)
        return seg_file
    score = _asr_score(out, 0.0, spd + 0.30, text) if spd else -1.0
    syn_seg(st, idx, {'file': str(out), 'line': text, 'mode': 'native',
                      'score': score, 'line_ph': line_ph(line)})
    save_state(work, st)
    print('seg%d 原生台词 ASR=%.2f（H3 自己说，仅烧字幕不求替换音轨）' % (idx, score), flush=True)
    return str(out)


def cmd_run(args) -> int:
    story = load_story(Path(args.story))
    # 缺省参数回退到 story JSON（CLI 未给定时不重复写）
    args.resolution = args.resolution or str(story.get('resolution') or '480p')
    args.seconds = int(args.seconds or int(story.get('seconds') or 4))
    args.lora = args.lora or str(story.get('lora') or 'fl2v_4step')
    args.seed = int(args.seed or int(story.get('seed') or 20260909))
    if args.fresh:
        import shutil
        if state_path(Path(args.work_dir)).exists():
            state_path(Path(args.work_dir)).unlink()
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    st = load_state(work, story)
    lines = story.get('lines') or {}
    # 台词先行×时长匹配（2026-09-09 用户批评'视频结束还没说完'）：
    #   台词段先合成台词音频预览 → 按音长定视频秒数（eff_seconds=音长+0.8s 余量），
    #   再生成画面（生成长度与台词匹配）；指纹含秒数（台词变化→秒数变→重做）。
    if str(PROJECT_ROOT / 'runs') not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / 'runs'))
    import h3.tts as _tts
    plan = []          # (prompt, ph, sec, line_or_None)
    for idx, seg in enumerate(story['segments']):
        line = lines.get(str(idx))
        prompt = build_prompt(seg, story, line, getattr(args, 'voice_mode', 'native'))
        eff_sec = int(args.seconds)
        qph = prompt_hash(prompt)
        if line:
            # 时长匹配（2026-09-09）：台词先行→按文本长度估算秒数（0.36s/字 + 1s 余量，
            # 实测中速朗读≈0.30-0.34s/字；取 0.36 保证语音在画面内说完）——
            # 不预合成音频（cosy CPU 合成过慢会拖死流程），正式合成在 run_line 一步完成。
            n_ch = len(str(line.get('text') or '').strip())
            eff_sec = max(int(args.seconds), int(math.ceil(n_ch * 0.36)) + 1)
            print('seg%d 台词 %d 字 → 视频 %ds（台词匹配估算）' % (idx, n_ch, eff_sec),
                  flush=True)
        qph = prompt_hash(prompt + '|sec=%d' % eff_sec)
        plan.append((prompt, qph, eff_sec, line))
    # 画面链断点（指纹含台词段秒数）与台词链断点（line_ph）分离：
    first_screen = None
    for idx, (prompt, qph, eff_sec, line) in enumerate(plan):
        if not seg_done(st, idx) or st['segments'][str(idx)].get('ph') != qph:
            first_screen = idx
            break
    lphs = {str(i): line_ph(line) for i, line in lines.items()}
    if first_screen is not None:
        print('RESUME: 画面链 seg%d 起重做（前 %d 段保留；指纹不一致或文件缺失）'
              % (first_screen, first_screen), flush=True)
    else:
        print('RESUME: 画面链全部就绪', flush=True)
    segs = {}
    prev_file = ''
    for idx, (prompt, qph, eff_sec, line) in enumerate(plan):
        screen_redo = first_screen is not None and idx >= first_screen
        need_line = bool(line) and not (
            bool(st['segments'].get(str(idx), {}).get('line'))
            and st['segments'].get(str(idx), {}).get('line_ph') == lphs.get(str(idx)))
        s_cur = st['segments'].get(str(idx), {}) or {}
        if not screen_redo and not need_line:
            file = s_cur['file']
            print('seg%d 已存在（resume 跳过）: %s' % (idx, Path(file).name), flush=True)
            segs[idx] = file
        else:
            if not screen_redo and need_line:
                # 台词独立重做：画面复用源段（src_file），不重新生成
                file = s_cur.get('src_file') or s_cur.get('file')
                print('seg%d 台词重做（画面复用 %s; voice=%s speed=%s）'
                      % (idx, Path(file).name, line.get('voice'), line.get('speed')),
                      flush=True)
            else:
                prev_frame = Path(prev_file) if prev_file and Path(prev_file).is_file() else None
                file = run_segment(idx, prompt, prev_frame, args, work, st, story,
                                   sec=eff_sec)
            segs[idx] = file
            if line:
                out_seg = work / ('seg_%02d_v.mp4' % idx)
                if str(getattr(args, 'voice_mode', 'native')) == 'native':
                    file = run_line_native(idx, file, line, out_seg, work, st)
                else:
                    file = run_line(idx, file, line, args, work, st)
                segs[idx] = file
        prev_file = segs.get(idx, file)
        # 末帧优先：更新 prev_frame 用本段实际文件的末帧（若本段刚跑已提取 last_）
        lf = work / ('last_%d.png' % idx)
        if lf.is_file():
            prev_file = str(lf)
        else:
            v = Path(segs.get(idx, ''))
            if v and v.is_file() and _last_frame(v, lf):
                prev_file = str(lf)
    # 拼接
    if args.stitch:
        seg_paths = [segs[i] for i in range(len(story['segments']))]
        keep = [str(i) for i, seg in enumerate(story['segments'])
                if (story.get('lines') or {}).get(str(i))]
        cmd = ['python3', str(STITCH), '--segments', ','.join(seg_paths), '--out', args.out,
               '--strip-audio', '--keep-audio-segs', ','.join(keep),
               '--ambience', str(getattr(args, 'ambience', 'room') or 'room'),
               '--ambience-under-speech']        # 故事片=叙事片，全片底噪连续更像成片
        print('== stitch keep-audio-segs=%s' % ','.join(keep), flush=True)
        r = _run(cmd, timeout=int(args.timeout))
        log = (r.stdout or '') + (r.stderr or '')
        print(log[-800:], flush=True)
        return 0 if r.returncode == 0 else 2
    print('ALL_SEGMENTS_DONE: %d 段（未 --stitch）' % len(story['segments']), flush=True)
    return 0


def cmd_status(args) -> int:
    story = load_story(Path(args.story))
    work = Path(args.work_dir)
    st = load_state(work, story)
    n = len(story['segments'])
    done = [i for i in range(n) if seg_done(st, i)]
    lines = (story.get('lines') or {})
    line_done = [i for i in lines if bool(st['segments'].get(str(i), {}).get('line'))]
    print('story=%s 段=%d 完成=%d 台词完成=%s' % (story.get('title'), n, len(done), line_done))
    for i in range(n):
        s = st['segments'].get(str(i), {}) or {}
        l = ('台词:%s' % 'OK' if s.get('line') else '')
        print('  seg%d %s %s' % (i, 'DONE' if i in done else 'PEND', l))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('故事片主控（剧本→分镜→台词→成片；可断点续跑）')
    ap.add_argument('--story', required=True, help='story JSON（title/style/characters/segments/lines）')
    ap.add_argument('--resolution', default='')
    ap.add_argument('--seconds', type=int, default=0)
    ap.add_argument('--lora', default='')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--work-dir', default='/tmp/story_film')
    ap.add_argument('--stitch', action='store_true')
    ap.add_argument('--voice-mode', default='native', choices=['native', 'tts'],
                    help='native(默认)=台词写进提示词由 H3 自己说+字幕原文(不重新配音)；tts=旧行为(CosyVoice 配音替换原轨)')
    ap.add_argument('--ambience', default='room', choices=['room', 'rain', 'none'],
                    help='无台词段铺的底噪（默认 room=房间底噪；拼接时生效）')
    ap.add_argument('--out', default='/tmp/story_film.mp4')
    ap.add_argument('--timeout', type=int, default=7200,
                    help='每步子进程超时秒（默认 7200；单段生成/台词链/拼接都在内）')
    ap.add_argument('--fresh', action='store_true', help='忽略进度强制从段0 重跑')
    ap.add_argument('--status', action='store_true', help='只打印进度')
    args = ap.parse_args(argv)
    story_path = Path(args.story)
    if not story_path.is_file():
        print('[错误] story 不存在: %s' % story_path, file=sys.stderr)
        return 3
    if args.status:
        return cmd_status(args)
    try:
        return cmd_run(args)
    except RuntimeError as e:
        print('[错误] %s（进度已保存，可重新运行 --status/再次运行续跑）' % e, file=sys.stderr)
        return 4
    except subprocess.TimeoutExpired:
        print('[错误] 子步骤超时（进度已保存；重新运行 resume 续跑）', file=sys.stderr)
        return 5


if __name__ == '__main__':
    sys.exit(main())
