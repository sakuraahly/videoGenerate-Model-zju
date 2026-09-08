#!/usr/bin/env python3
"""真实台词口型链（agent run_script 一键）：角色真的说出设定台词。

2026-09-08 用户定案："强化工作流——视频台词=真台词（非模型伪英语）"。
链路：
  1) 台词 TTS（cosy 自然音色；voice 默认 yunxi 中文男）→ line.wav；
  2) Wav2Lip（gan+s3fd，帧对齐 mel+PNG 序列封装——已修补）把 line.wav 驱动到人物嘴型
     （人物真的在说这段台词）→ 产出已含台词音轨的成片；
  3) keep 语义收尾：台词字幕（楷体默认）+ 可选旁白垫轨（-15dB）→ 最终成片；
  4) --asr-check：SenseVoice 回环比对（台词原文）→ 验证"真的说对了"。

用法（agent/引擎侧）：
  python runs/h3/lipsync_chain.py --video <人脸源视频> --line "台词"       [--voice yunxi|xiaoxiao|aria|daler] [--narration "旁白"] [--subtitle-style kai]       [--asr-check] [--out <路径>]

依赖：~/ai/tts-venv（torch/cv2/onnxruntime…）、~/ai/cosy-venv、~/ai/wav2lip/src、模型
（wav2lip_gan/s3fd、GFPGANv1.4.onnx 可选 --face-restore）；GPU 推理（Wav2Lip）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
W2L_SRC = Path(os.path.expanduser('~/ai/wav2lip/src/Wav2Lip-master'))
TTS_PY = Path(os.path.expanduser('~/ai/tts-venv/bin/python3'))
COSY_PY = Path(os.path.expanduser('~/ai/cosy-venv/bin/python3'))
ASR_PY = Path(os.path.expanduser('~/ai/asr-venv/bin/python3'))
CKPT = Path(os.path.expanduser('~/ai/wav2lip/checkpoints/wav2lip_gan.pth'))
S3FD = Path(os.path.expanduser('~/ai/wav2lip/checkpoints/s3fd-619a316812.pth'))

_VOICE_FULL = {'xiaoxiao': 'zh-CN-XiaoxiaoNeural', 'yunxi': 'zh-CN-YunxiNeural',
               'aria': 'en-US-AriaNeural', 'daler': 'en-US-ChristopherNeural'}


def _run(cmd, timeout=1800, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError('fail: ' + ((r.stderr or r.stdout) or '')[-600:])
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser('真实台词口型链（Wav2Lip 驱动设定台词）')
    ap.add_argument('--video', default='', help='人脸源视频（人物说话/近景）；缺省=自动取 ComfyUI output/video 最近生成 MiniMax_H3_*.mp4')
    ap.add_argument('--line', required=True, help='台词（角色真实说的话）')
    ap.add_argument('--voice', default='yunxi', choices=list(_VOICE_FULL))
    ap.add_argument('--narration', default='', help='旁白（垫轨 -15dB，不影响台词）')
    ap.add_argument('--subtitle-style', default='kai')
    ap.add_argument('--subtitle-font', default='kai')
    ap.add_argument('--subtitle-color', default='auto')
    ap.add_argument('--backend', default='cosy')
    ap.add_argument('--asr-check', action='store_true')
    ap.add_argument('--face-restore', action='store_true', help='顺带 GFPGAN 人脸修复（更耗时长）')
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    src = Path(args.video)
    if not src.is_file():
        # 自动选最新生成人脸近景（agent 无需关心素材定位）
        import glob
        vids = sorted(glob.glob(str(Path(os.path.expanduser('~/ai/ComfyUI/output/video')) + '/MiniMax_H3_*.mp4')),
                      key=os.path.getmtime, reverse=True)
        if not vids:
            print('[错误] 未指定 --video 且 output/video 无 MiniMax_H3_*.mp4', file=sys.stderr)
            return 3
        src = Path(vids[0])
        print('AUTO_VIDEO: %s' % src, flush=True)
    if not src.is_file():
        print('[错误] 视频不存在: %s' % src, file=sys.stderr)
        return 3
    out = Path(args.out) if args.out else Path('/tmp/lipsync_out.mp4')
    work = Path('/tmp/lipsync_chain')
    work.mkdir(parents=True, exist_ok=True)

    # 0) 清理 Wav2Lip 临时帧/旧产物（防串帧）
    for d in (W2L_SRC / 'temp' / 'frames', W2L_SRC / 'temp'):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    for f in [work / 'line.wav', work / 'face.mp4', out]:
        f.unlink(missing_ok=True)
    s3fd_dst = W2L_SRC / 'face_detection' / 'detection' / 'sfd' / 's3fd.pth'
    if not s3fd_dst.exists() and S3FD.exists():
        shutil.copy2(S3FD, s3fd_dst)

    # 1) 台词 TTS
    ref = REPO / 'assets' / 'tts_refs' / f'{args.voice}.wav'
    ref_txt = (REPO / 'assets' / 'tts_refs' / f'{args.voice}.txt').read_text(encoding='utf-8').strip()
    if not ref.is_file():
        print('[错误] 参考样本缺失: %s' % ref, file=sys.stderr)
        return 3
    _run([str(COSY_PY), str(REPO / 'runs' / 'h3' / 'tts_cosy_check.py'),
          '--text', args.line, '--ref-file', str(ref), '--ref-text', ref_txt,
          '--output', str(work / 'line.wav')])
    print('TTS_OK: %s' % (work / 'line.wav'), flush=True)

    # 2) Wav2Lip（真实台词驱动嘴型；输出已含台词音轨）
    src_cp = work / 'face.mp4'
    shutil.copy2(src, src_cp)
    raw_out = work / 'lipsync_raw.mp4'
    _run([str(TTS_PY), str(W2L_SRC / 'inference.py'),
          '--checkpoint_path', str(CKPT), '--face', str(src_cp),
          '--audio', str(work / 'line.wav'), '--outfile', str(raw_out)],
         timeout=3600, cwd=W2L_SRC)
    if not raw_out.is_file():
        print('[错误] Wav2Lip 未产出（检查人脸可检测性/GPU）', file=sys.stderr)
        return 4
    print('W2L_OK: %s' % raw_out, flush=True)

    # 3) keep 收尾：台词字幕（角色原声=台词音轨保留）；旁白=台词结束 0.6s 后开始（不重叠）
    sys.path.insert(0, str(REPO / 'runs'))
    import h3.tts as _tts
    line_dur = float(_tts.probe_duration(work / 'line.wav') or 0)  # probe? 用 ffprobe 兜底
    res = _tts.attach_speech_and_subtitle(
        raw_out, args.line, out=out, voice=_VOICE_FULL[args.voice],
        fontsize=0, backend=args.backend,
        subtitle_style=args.subtitle_style, subtitle_font=args.subtitle_font,
        subtitle_color=args.subtitle_color,
        audio_mode='keep', subtitle_source='text',
        narration='')  # 旁白错开在下方单独混入
    nar = str(args.narration or '').strip()
    if nar:
        # 旁白 TTS
        nar_wav = work / 'narration.wav'
        nar_wav.unlink(missing_ok=True)
        _run([str(COSY_PY), str(REPO / 'runs' / 'h3' / 'tts_cosy_check.py'),
              '--text', nar, '--ref-file', str(ref), '--ref-text', ref_txt,
              '--output', str(nar_wav)])
        video_dur = float(_tts.probe_duration(res['path']) or line_dur or 3.0)
        start = line_dur + 0.6                     # 台词结束 0.6s 后
        narr_end = start + float(_tts.probe_duration(nar_wav) or 2.0)
        pad = max(0.0, narr_end - video_dur)
        ms = int(start * 1000)
        fcmd = ['ffmpeg', '-y', '-i', str(res['path']), '-i', str(nar_wav),
                '-map', '0:v', '-map', '[ot]', '-c:v', 'copy',
                '-filter_complex',
                '[1:a]volume=0.18,adelay=%d:all=1[na];[0:a][na]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[ot]' % ms]
        if pad > 0:
            fcmd[6:6] = ['-vf', 'tpad=stop_mode=clone:stop_duration=%.2f' % pad]
        fcmd += ['-c:a', 'aac', '-b:a', '192k', str(out)]
        nr = subprocess.run(fcmd, capture_output=True, text=True, timeout=1800)
        if nr.returncode != 0:
            raise RuntimeError('旁白混入失败: ' + (nr.stderr or '')[-300:])
        print('NARRATION: start=%.2fs dur=%.2fs pad=%.2fs' % (start, narr_end - start, pad), flush=True)
    print('FINAL: %s %d' % (out, out.stat().st_size), flush=True)
    res = {'path': out, 'speech_dur': line_dur, 'srt': None, 'speech': '', 'asr_text': ''}

    # 4) 可选 ASR 验真（台词回环）
    if args.asr_check:
        r = subprocess.run([str(ASR_PY), str(REPO / 'runs' / 'h3' / 'asr_check.py'),
                            str(res['path']), '--compare', args.line],
                           capture_output=True, text=True, timeout=600)
        print(r.stdout.strip()[-600:], flush=True)
    print('DONE_LIPSYNC_CHAIN', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
