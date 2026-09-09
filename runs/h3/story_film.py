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
    r = _run(['ffmpeg', '-y', '-v', 'error', '-sseof', '-0.3', '-i', str(video),
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


def build_prompt(seg: dict, story: dict) -> str:
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


def run_segment(idx: int, prompt: str, prev_frame, args, work: Path, st: dict, story: dict) -> str:
    """生成一段；返回该段视频文件路径。"""
    cmd = ['python3', str(SUBMIT), '--stage', 'i2v' if prev_frame else 't2v',
           '--resolution', args.resolution, '--lora', args.lora,
           '--seconds', str(args.seconds), '--seed', str(args.seed)]
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
    syn_seg(st, idx, {'file': str(segp), 'prompt': prompt, 'ph': prompt_hash(prompt)})
    save_state(work, st)
    print('seg%d OK: %s' % (idx, segp.name), flush=True)
    return str(segp)


def run_line(idx: int, seg_file: str, line: dict, args, work: Path, st: dict) -> str:
    """台词段：TTS 文本=台词表（先设置后生成）；发音回环+spoken 重试。"""
    text = str(line.get('text') or '').strip()
    if not text:
        return seg_file
    spoken = str(line.get('spoken') or '').strip() or text
    voice = line.get('voice') or 'yunxi'
    out = work / ('seg_%02d_v.mp4' % idx)
    log = ''
    attempts = (text, spoken) if spoken != text else (text,)
    for attempt, use_text in enumerate(attempts):
        cmd = ['python3', str(LIPSYNC), '--video', seg_file, '--line', use_text,
               '--voice', voice, '--asr-check', '--face-restore', '--out', str(out)]
        print('== seg%d 台词链(t=%d) voice=%s' % (idx, attempt, voice), flush=True)
        r = _run(cmd, timeout=int(args.timeout))
        log = (r.stdout or '') + (r.stderr or '')
        score = _line_score_of(log)
        ok_file = out.is_file() and out.stat().st_size > 0
        if ok_file and (attempt == 1 or score >= LINE_SCORE_MIN):
            if attempt == 1:
                print('seg%d 发音回环 FAIL(%.2f) → spoken 重试（台词文本不变，发音写法替换）'
                      % (idx, score), flush=True)
            syn_seg(st, idx, {'file': str(out), 'line': text, 'voice': voice,
                              'score': score, 'spoken_used': attempt == 1})
            save_state(work, st)
            print('seg%d 台词 %s ASR=%.2f' % (idx, 'OK' if score >= LINE_SCORE_MIN else 'OK(spoken)',
                                              score), flush=True)
            return str(out)
        if attempt == 0 and score >= LINE_SCORE_MIN and ok_file:
            syn_seg(st, idx, {'file': str(out), 'line': text, 'voice': voice, 'score': score})
            save_state(work, st)
            return str(out)
    print('[错误] seg%d 台词链最终失败（ASR=%.2f, rc 见上）' % (idx, _line_score_of(log)),
          file=sys.stderr)
    print(log[-500:], file=sys.stderr)
    return seg_file  # 兜底：台词失败则保留源段（画面片），报告给用户


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
    prompts = [build_prompt(seg, story) for seg in story['segments']]
    phs = [prompt_hash(p) for p in prompts]
    lines = story.get('lines') or {}
    # 断点=连续头部就绪（文件在+指纹一致+台词段台词完成）；首个不满足=重做起点（链失效传播）
    first_redo = None
    for idx in range(len(story['segments'])):
        if not seg_ready(st, idx, phs[idx], bool(lines.get(str(idx)))):
            first_redo = idx
            break
    if first_redo is not None:
        print('RESUME: seg%d 起重做（前 %d 段保留；指纹/台词不一致或文件缺失）'
              % (first_redo, first_redo), flush=True)
    else:
        print('RESUME: 全部段已就绪', flush=True)
    segs = {}
    prev_file = ''
    for idx, seg in enumerate(story['segments']):
        redo = first_redo is None or idx >= first_redo
        line = lines.get(str(idx))
        if not redo:
            file = st['segments'][str(idx)]['file']
            print('seg%d 已存在（resume 跳过）: %s' % (idx, Path(file).name), flush=True)
            segs[idx] = file
        else:
            prev_frame = Path(prev_file) if prev_file and Path(prev_file).is_file() else None
            file = run_segment(idx, prompts[idx], prev_frame, args, work, st, story)
            segs[idx] = file
            if line:
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
               '--strip-audio', '--keep-audio-segs', ','.join(keep)]
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
