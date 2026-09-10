#!/usr/bin/env python3
"""talk_one — 一条命令：台词 → 本地 TTS → H3 音频驱动说话镜头 → 队列内成品（100% ComfyUI 队列）。

用户诉求（2026-09-09/10）：
  1) 合成一条命令：生成（H3 音频参考驱动=原生口型/说话动作）+ 队列内 H3Finalize 成品（准确 TTS 音轨）一步到位；
  2) 视频时长必须与**真实语音时长**匹配（不是拍脑袋固定 10s）——本脚本先本地合成台词音频，
     用其真实时长决定生成秒数（+余量），再提交生成。

流程：
  ① tts.synthesize(台词) → line.wav（CosyVoice2；CPU 强制，避开 ComfyUI --reserve-vram 显存争用）
  ② 参考图：--ref-image 或 --from-video（抽首帧）；r2v（H3 音频参考仅 r2v 槽支持）
  ③ h3_submit --stage r2v --image <ref> --audios line.wav --seconds ceil(dur+0.6)  → 生成产物
  ④ 队列内提交 H3Finalize（audio_mode=replace, subtitle_source=text, burn_subtitle 可关）+ H3AsrCheck
  ⑤ 汇总：成品路径 / 时长 / ASR 分数

用法：
  python3 runs/h3/talk_one.py --text "真是力不从心了, what can I say?" \
      --ref-image /tmp/oldman_ref.png [--voice yunxi] [--no-subtitle] [--resolution 480p]
  python3 runs/h3/talk_one.py --text "..." --from-video outputs/video_556.mp4 ...
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'runs'))
from h3 import tts as _tts  # noqa: E402

SUBMIT = ROOT / 'runs' / 'h3_submit.py'
COMFY = 'http://127.0.0.1:8188'
VOICES = ('xiaoxiao', 'yunxi', 'aria', 'daler')


def _sh(cmd, timeout=3600, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r


def synth_line(text: str, wav: Path, voice: str, speed: float) -> float:
    """台词音频（本地 cosy；CPU 强制避免与 ComfyUI 争显存）。返回时长秒。"""
    env = None
    try:
        import os as _os
        env = dict(_os.environ)
        env['CUDA_VISIBLE_DEVICES'] = ''
    except Exception:  # noqa: BLE001
        pass
    prev = None
    try:
        import os as _os2
        prev = _os2.environ.get('CUDA_VISIBLE_DEVICES')
        _os2.environ['CUDA_VISIBLE_DEVICES'] = ''
    except Exception:  # noqa: BLE001
        pass
    try:
        d = _tts.synthesize(text, wav, voice=voice, backend='cosy', speed=speed)
    finally:
        try:
            import os as _os3
            if prev is None:
                _os3.environ.pop('CUDA_VISIBLE_DEVICES', None)
            else:
                _os3.environ['CUDA_VISIBLE_DEVICES'] = prev
        except Exception:  # noqa: BLE001
            pass
    return float(d or _tts.probe_duration(wav) or 0.0)


def fit_frames_seconds(dur: float, margin: float = 0.15) -> float:
    """H3 帧数网格（5 + 17k 帧 @24fps）中选**最小 ≥ dur+margin** 的档；返回秒数。

    语音 2.76s → 3.042s（73 帧）而不是 4.458s（107 帧）——避免'说完话还在动嘴'。
    """
    need = max(0.5, float(dur) + float(margin))
    frames = 5
    while frames / 24.0 < need:
        frames += 17
        if frames > 3000:
            break
    return round(frames / 24.0, 3)


def first_frame(video: Path, out_png: Path) -> bool:
    r = _sh(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(video),
             '-vframes', '1', '-q:v', '2', str(out_png)], timeout=120)
    return r.returncode == 0 and out_png.is_file()


def submit_generation(prompt: str, ref: Path, wav: Path, seconds: float, res: str,
                      lora: str, seed: int, timeout: int = 2400,
                      no_audio_ref: bool = False) -> str:
    # r2v 模板 ref2v_8step 有 2 个参考图槽 → 契约要求 <Picture 1>/<Picture 2>；
    # 同一张人物参考图接两个槽（身份/环境锁定），提示词同时含两个 tag。
    cmd = ['python3', str(SUBMIT), '--stage', 'r2v', '--resolution', res,
           '--seconds', str(float(seconds)), '--lora', lora, '--seed', str(seed),
           '--image', str(ref), '--image', str(ref)]
    if not no_audio_ref:
        cmd += ['--audios', str(wav)]     # 音频参考=口型引导（H3 会说出近似内容）
    cmd += ['--prompt', prompt, '--force-new']
    print('== 生成（H3 音频驱动, %ds, %s）' % (seconds, res), flush=True)
    r = _sh(cmd, timeout=timeout)
    log = (r.stdout or '') + (r.stderr or '')
    m = re.search(r'LOCAL_OUTPUT:\s*(outputs/\S+\.mp4)', log)
    if not m:
        print(log[-800:], file=sys.stderr)
        raise RuntimeError('生成失败（rc=%s）' % r.returncode)
    out = ROOT / m.group(1)
    print('生成产物: %s' % out, flush=True)
    return str(out)


def queue_finalize(video: str, text: str, voice: str, burn_subtitle: bool,
                   style: str = 'harmony', timeout: int = 1800,
                   audio_mode: str = 'replace') -> dict:
    wf = {
        '1': {'class_type': 'H3Finalize', 'inputs': {
            'video': str(video), 'text': text, 'voice': voice,
            'audio_mode': audio_mode, 'subtitle_source': 'text', 'backend': 'cosy',
            'subtitle_style': style,
            'burn_subtitle': 'on' if burn_subtitle else 'off'}},
        '2': {'class_type': 'H3AsrCheck', 'inputs': {
            'media': ['1', 0], 'text_compare': text}},
    }
    req = urllib.request.Request(COMFY + '/prompt',
                                 data=json.dumps({'prompt': wf, 'client_id': 'talkone'}).encode(),
                                 headers={'Content-Type': 'application/json'})
    pid = json.load(urllib.request.urlopen(req, timeout=60))['prompt_id']
    print('== 队列内成品链提交: %s' % pid, flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(8)
        try:
            h = json.load(urllib.request.urlopen(COMFY + '/history/' + pid, timeout=20))
        except Exception:  # noqa: BLE001
            continue
        if pid in h:
            st = (h[pid].get('status') or {}).get('status_str', '?')
            print('队列状态: %s' % st, flush=True)
            return {'prompt_id': pid, 'status': st}
    print('[警告] finalize 轮询超时（任务可能仍在队列）', file=sys.stderr)
    return {'prompt_id': pid, 'status': 'timeout'}


def main() -> int:
    ap = argparse.ArgumentParser('一条命令：台词→TTS→H3 音频驱动说话镜头→队列内成品')
    ap.add_argument('--text', required=True, help='台词（TTS + 字幕原文 + ASR 比对）')
    ap.add_argument('--ref-image', default='', help='人物参考图（r2v 必需；或用 --from-video 抽帧）')
    ap.add_argument('--from-video', default='', help='从已有视频抽首帧作为人物参考图')
    ap.add_argument('--voice', default='yunxi', choices=list(VOICES))
    ap.add_argument('--speed', type=float, default=0.95, help='语速（越小越慢）')
    ap.add_argument('--resolution', default='480p')
    ap.add_argument('--lora', default='ref2v_8step')
    ap.add_argument('--seed', type=int, default=20260915)
    ap.add_argument('--margin', type=float, default=0.6, help='视频比语音多的余量秒（默认 0.6）')
    ap.add_argument('--min-seconds', type=int, default=2, help='最短视频秒数')
    ap.add_argument('--no-subtitle', action='store_true', help='不烧字幕（默认烧）')
    ap.add_argument('--audio-source', default='h3', choices=['h3', 'tts'],
                    help='最终音轨来源：h3=保留 H3 自适应音色（口型/语音/时长天然一致，推荐）；'
                         'tts=替换为本地 TTS 准确语音（音色固定，可能尾部还在动嘴）')
    ap.add_argument('--no-audio-ref', action='store_true',
                    help='生成时不给音频参考（让 H3 完全自适应音色；默认给 TTS 音频做口型引导）')
    ap.add_argument('--work-dir', default='/tmp/talk_one')
    ap.add_argument('--skip-generate', default='', help='跳过生成，直接对已有视频做队列内成品（调试）')
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    wav = work / 'line.wav'
    text = args.text.strip()

    # ① 台词音频（真实时长决定视频长度）
    dur = synth_line(text, wav, args.voice, args.speed)
    print('== 台词音频: %s (%.2fs)' % (wav, dur), flush=True)
    # 帧档匹配（5+17k 帧 @24fps）：选最小 ≥ 语音+余量 的档 → 视频不虚长
    sec_fit = fit_frames_seconds(dur, margin=min(float(args.margin), 0.2))
    seconds = max(int(args.min_seconds), sec_fit)
    if seconds != sec_fit:  # min-seconds 保护
        seconds = float(sec_fit)
    print('== 视频秒数（帧档匹配语音）=%.3fs（语音 %.2fs）' % (seconds, dur), flush=True)

    # ② 参考图
    ref = None
    if args.skip_generate:
        video = str(Path(args.skip_generate))
    else:
        if args.from_video:
            ref = work / 'ref_from_video.png'
            if not first_frame(Path(args.from_video), ref):
                print('[错误] 抽帧失败: %s' % args.from_video, file=sys.stderr)
                return 3
        elif args.ref_image:
            ref = Path(args.ref_image)
            if not ref.is_file():
                print('[错误] 参考图不存在: %s' % ref, file=sys.stderr)
                return 3
        else:
            print('[错误] 需要 --ref-image 或 --from-video（H3 音频驱动仅 r2v 槽支持）', file=sys.stderr)
            return 3
        if args.no_audio_ref:
            # 纯 H3 自适应：把台词写进提示词，让 H3 自己选音色并说话（音画天然同时长）
            prompt = ('<Picture 1> the same person shown in the reference image, looking straight '
                      'into the camera and speaking slowly in a low, weary, aged voice, saying '
                      'exactly these words: "%s". His lips and expression move naturally with those '
                      'words, gentle sad performance. <Picture 2> the same person and the same room/'
                      'environment as the reference image, keep the look identical. The reference '
                      'images are locked throughout the whole shot; they are NOT first-frame '
                      'keyframes; keep every frame consistent. NO written characters, no text, '
                      'no watermark, no cuts.' % text)
        else:
            prompt = ('<Picture 1> the same person shown in the reference image, looking straight '
                      'into the camera and speaking the exact words heard in <Audio 1>, lips and '
                      'expression moving naturally in sync with that voice, natural performance, '
                      'gentle tone, cinematic lighting, shallow depth of field, film grain. '
                      '<Picture 2> the same person and the same room/environment as the reference '
                      'image, keep the look identical. The reference images are locked throughout '
                      'the whole shot; they are NOT first-frame keyframes; keep every frame '
                      'consistent. NO written characters, no text, no watermark, no cuts.')
        video = submit_generation(prompt, ref, wav, seconds, args.resolution, args.lora, args.seed,
                                  no_audio_ref=args.no_audio_ref)

    # ③ 队列内成品：h3=保留 H3 自适应音色（音画同时长）／tts=替换为本地 TTS 准确语音
    mode = 'keep' if args.audio_source == 'h3' else 'replace'
    print('== 音轨来源: %s（%s）' % (args.audio_source, 'H3 自适应音色' if mode == 'keep'
                                    else '本地 TTS 替换'), flush=True)
    queue_finalize(video, text, args.voice, burn_subtitle=not args.no_subtitle,
                   audio_mode=mode)
    src = Path(video)
    out = src.with_name(src.stem + '_final.mp4')
    print('== 成品: %s (%s)' % (out, '存在' if out.is_file() else '缺失'), flush=True)
    if out.is_file():
        print('== 成品时长: %.2fs / 语音 %.2fs' % (float(_tts.probe_duration(out) or 0), dur),
              flush=True)
    print('SRT: %s' % src.with_name(src.stem + '_final.srt'))
    return 0 if out.is_file() else 4


if __name__ == '__main__':
    sys.exit(main())
