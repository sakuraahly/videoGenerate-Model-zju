#!/usr/bin/env python3
"""真实台词口型链（agent run_script 一键）：角色真的说出设定台词。

2026-09-08 用户定案："强化工作流——视频台词=真台词（非模型伪英语）"。
链路：
  1) 台词 TTS（cosy 自然音色；voice 默认 yunxi 中文男）→ line.wav；
  2) Wav2Lip（gan+s3fd，帧对齐 mel+PNG 序列封装——已修补）把 line.wav 驱动到人物嘴型
     （人物真的在说这段台词）→ 产出已含台词音轨的成片；
  3) keep 语义收尾：台词字幕（楷体默认）+ 可选旁白垫轨（-15dB）→ 最终成片；
  4) --asr-check：双轨 ASR 验真——台词窗 [0, line_dur] 单独打分（LINE_ASR/LINE_SCORE，
     免受旁白混判干扰）+ 旁白窗存在性/打分（NARRATION_ASR/NARRATION_SCORE，非重叠窗）；
  5) 产物归宿（§15d）：ComfyUI 输出区 + 仓库 outputs + 会话结果区
     logs/agent_chats/<cid>/outputs/（env VIDEOGEN_SESSION_CID 由 run_script 注入；
     页面 7860 结果区预览/下载），保留最近 10 个/会话。

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

# 2026-09-08：agent run_script 用 qwen-agent-venv（无 cv2/onnxruntime）——重投递须在 import cv2 之前
_TTS_PY = Path(os.path.expanduser('~/ai/tts-venv/bin/python3'))
if sys.executable != str(_TTS_PY) and _TTS_PY.is_file():
    try:
        import cv2  # noqa: F401
    except ImportError:
        print('REEXEC_TTS_VENV', flush=True)
        os.execv(str(_TTS_PY), [str(_TTS_PY), os.path.abspath(__file__)] + sys.argv[1:])

import cv2  # noqa: F401  人脸预检/预筛
import numpy as np  # noqa: F401  检测批处理

# TTS 子进程强制 CPU（ComfyUI/其他进程可能持 GPU 上下文；cosy 有 GPU→CPU 兜底，但会拖）
os.environ.setdefault('CUDA_VISIBLE_DEVICES', '')

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
        # 自动选最新生成的近景人脸素材（先做检测预筛；agent 无需关心素材定位）
        import glob
        vids = sorted(glob.glob(str(os.path.expanduser('~/ai/ComfyUI/output/video')) + '/MiniMax_H3_*.mp4'),
                      key=os.path.getmtime, reverse=True)
        chosen = None
        seen = []
        try:
            sys.path.insert(0, str(W2L_SRC))
            from face_detection import FaceAlignment, LandmarksType  # noqa: E402
            det = FaceAlignment(LandmarksType._2D, flip_input=False, device='cpu')
            for v in vids[:8]:
                cap = cv2.VideoCapture(str(v))
                ok, f = cap.read()
                mid = None
                # 取约 40% 处一帧（避开起手遮挡）
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if n > 10:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.4))
                    ok, f = cap.read()
                cap.release()
                if not ok or f is None:
                    continue
                import numpy as _np
                rect = det.get_detections_for_batch(_np.array([f]))[0]
                seen.append((Path(v).name, bool(rect)))
                if rect:
                    chosen = Path(v)
                    break
        except Exception as _e:  # noqa: BLE001
            print('[warn] 人脸预筛不可用: %s（回退最新）' % _e, file=sys.stderr)
        if chosen is None and vids:
            chosen = Path(vids[0])
        if chosen is None:
            print('[错误] 未指定 --video 且 output/video 无 MiniMax_H3_*.mp4', file=sys.stderr)
            return 3
        src = chosen
        print('AUTO_VIDEO: %s  scan=%s' % (src.name, seen[:5]), flush=True)
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

    # 2) 人脸预检/修剪：逐帧采样（步长 4），无脸段裁掉（起手遮挡等）→ 最长连续有脸区间
    def _face_run(video: Path):
        try:
            import numpy as _np
            sys.path.insert(0, str(W2L_SRC))
            from face_detection import FaceAlignment, LandmarksType  # noqa: E402
            det = FaceAlignment(LandmarksType._2D, flip_input=False, device='cpu')
            cap = cv2.VideoCapture(str(video))
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            states = []
            idx = 0
            while True:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, f = cap.read()
                if not ok or f is None:
                    break
                r0 = det.get_detections_for_batch(_np.array([f]))[0]
                states.append(bool(r0))
                idx += 4
            cap.release()
        except Exception:  # noqa: BLE001
            return None
        if not states:
            return None
        # 最长连续有脸区间（返回帧区间）
        best_s = best_l = s = 0
        cur = 0
        for i, st in enumerate(states):
            if st:
                if cur == 0:
                    s = i
                cur += 1
                if cur > best_l:
                    best_l, best_s = cur, s
            else:
                cur = 0
        t0 = best_s * 4 / fps
        t1 = (best_s + best_l) * 4 / fps
        return t0, t1

    src_face = src
    run = _face_run(src)
    if run and run[1] - run[0] >= 1.2:
        t0, t1 = run
        src_face = work / 'face_run.mp4'
        _run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', '%.2f' % t0,
              '-to', '%.2f' % t1, '-i', str(src), '-c', 'copy', str(src_face)])
        print('FACE_RUN: %.2fs->%.2fs' % (t0, t1), flush=True)
    elif run:
        print('[warn] 可检测人脸区间过短（%.2fs），按原片尝试' % (run[1] - run[0]), flush=True)
    src_cp = work / 'face.mp4'
    shutil.copy2(src_face, src_cp)
    # 补帧到台词全长（克隆末帧）：否则台词比脸源长时尾部被截断（2026-09-08 用户验证'话没讲完'→修复）
    sys.path.insert(0, str(REPO / 'runs'))
    from h3 import tts as _tts_prv
    line_dur = float(_tts_prv.probe_duration(work / 'line.wav') or 0)
    face_dur = float(_tts_prv.probe_duration(src_cp) or 0)
    if line_dur > face_dur + 0.15:
        pad_s = line_dur - face_dur + 0.20
        pad_out = work / 'face_pad.mp4'
        _run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src_cp),
              '-vf', 'tpad=stop_mode=clone:stop_duration=%.2f' % pad_s,
              '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', str(pad_out)])
        src_cp = pad_out
        print('FACE_PAD: %.2fs -> %.2fs (line %.2fs)' % (face_dur, face_dur + pad_s, line_dur),
              flush=True)
    raw_out = work / 'lipsync_raw.mp4'
    _run([str(TTS_PY), str(W2L_SRC / 'inference.py'),
          '--checkpoint_path', str(CKPT), '--face', str(src_cp),
          '--audio', str(work / 'line.wav'), '--outfile', str(raw_out)],
         timeout=3600, cwd=W2L_SRC)
    if not raw_out.is_file():
        print('[错误] Wav2Lip 未产出（检查人脸可检测性/GPU）', file=sys.stderr)
        return 4
    print('W2L_OK: %s' % raw_out, flush=True)

    # 2.5) --face-restore：整脸 GFPGAN 重渲染（自适应边距+泊松=吸收 Wav2Lip 贴皮框，无框）
    if args.face_restore:
        restored = work / 'lipsync_restored.mp4'
        fr_script = str(REPO / 'runs' / 'h3' / 'face_restore_video.py')
        _run([str(TTS_PY), fr_script, '--video', str(raw_out), '--out', str(restored),
              '--device', 'cpu'], timeout=3600)
        print('FACE_RESTORE_OK: %s' % restored, flush=True)
        raw_out = restored

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
    nar_dur = 0.0
    if nar:
        # 旁白 TTS（混入临时文件避免与源同路径）
        mix_out = work / 'mix.mp4'
        mix_out.unlink(missing_ok=True)
        nar_wav = work / 'narration.wav'
        nar_wav.unlink(missing_ok=True)
        _run([str(COSY_PY), str(REPO / 'runs' / 'h3' / 'tts_cosy_check.py'),
              '--text', nar, '--ref-file', str(ref), '--ref-text', ref_txt,
              '--output', str(nar_wav)])
        video_dur = float(_tts.probe_duration(res['path']) or line_dur or 3.0)
        start = line_dur + 0.6                     # 台词结束 0.6s 后
        nar_dur = float(_tts.probe_duration(nar_wav) or 2.0)
        narr_end = start + nar_dur
        pad = max(0.0, narr_end - video_dur)
        ms = int(start * 1000)
        # 2026-09-08 三修：amix 系引擎（含 dropout/归一化变体）会以不同方式伤台词尾——彻底改用
        # concat 顺序拼接：台词(0-3.56s) → apad 0.6s 静音 → 旁白。无混合、无淡出，台词必然完整。
        fc = ('[1:a]volume=0.18[na];[0:a]apad=pad_dur=0.52[a0];[a0][na]concat=n=2:v=0:a=1[aout]')
        fcmd = ['ffmpeg', '-y', '-i', str(res['path']), '-i', str(nar_wav),
                '-filter_complex', fc]
        if pad > 0:
            fc_v = 'tpad=stop_mode=clone:stop_duration=%.2f' % pad
            fcmd[7] = fc + ';[0:v]' + fc_v + '[vp]'  # fcmd[7]=filter_complex 的值槽
            fcmd += ['-map', '[vp]', '-map', '[aout]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        else:
            fcmd += ['-map', '0:v', '-map', '[aout]', '-c:v', 'copy']
        fcmd += ['-c:a', 'aac', '-b:a', '192k', str(mix_out)]
        nr = subprocess.run(fcmd, capture_output=True, text=True, timeout=1800)
        if nr.returncode != 0:
            raise RuntimeError('旁白混入失败: ' + (nr.stderr or '')[-300:])
        mix_out.replace(out)
        print('NARRATION: start=%.2fs dur=%.2fs pad=%.2fs' % (start, narr_end - start, pad), flush=True)
    print('FINAL: %s %d' % (out, out.stat().st_size), flush=True)
    res = {'path': out, 'speech_dur': line_dur, 'srt': None, 'speech': '', 'asr_text': ''}

    # 4) 双轨 ASR 验真（§15d 小项）：台词窗 [0, line_dur] 单独打分（免受旁白混判干扰）
    #    + 旁白窗存在性/打分（旁白从台词后 0.52s 静音垫开始，与台词不重叠）
    if args.asr_check:
        import re as _re2

        def _asr_win(tag, start, dur, cmp_txt):
            r = subprocess.run([str(ASR_PY), str(REPO / 'runs' / 'h3' / 'asr_check.py'),
                                str(res['path']), '--start', '%.3f' % start,
                                '--dur', '%.3f' % dur, '--compare', cmp_txt],
                               capture_output=True, text=True, timeout=600)
            txt = (r.stdout or '').strip()
            _at = _re2.search(r'^ASR_TEXT:\s*(.+)$', txt, _re2.M)
            _sc = _re2.search(r'^ASR_SCORE:\s*([\d.]+)$', txt, _re2.M)
            _mc = _re2.search(r'^ASR_MATCH:\s*(\w+)$', txt, _re2.M)
            print('%s_ASR: %s' % (tag, (_at.group(1) if _at else txt[-200:])), flush=True)
            if _sc:
                print('%s_SCORE: %s %s' % (tag, _sc.group(1),
                                           (_mc.group(1) if _mc else '')), flush=True)
            elif _at:
                print('%s_SCORE: (无比对文本)' % tag, flush=True)

        _asr_win('LINE', 0.0, line_dur + 0.30, args.line)
        if nar:
            _asr_win('NARRATION', line_dur + 0.45, nar_dur + 0.40, nar)
        else:
            print('NARRATION_ASR: (未设旁白)', flush=True)
    # 产物归宿（§15d）：ComfyUI 输出区（预览/下载）+ 仓库 outputs/——杜绝'找不到结果'
    import shutil as _sh
    import time as _tm
    # §15d 命名规范：lipsync_<时间戳>_<台词前4字>.mp4（全时间戳防跨日重名；先定义防单区失败后引用不到）
    name = 'lipsync_%s_%s.mp4' % (_tm.strftime('%Y%m%d_%H%M%S'), (args.line or 'line')[:4])
    dest_candidates = []
    try:
        outdir = Path(os.path.expanduser('~/ai/ComfyUI/output/video'))
        outdir.mkdir(parents=True, exist_ok=True)
        c_dst = outdir / name
        _sh.copy2(str(out), str(c_dst))
        dest_candidates.append(str(c_dst))
    except Exception as _e:  # noqa: BLE001
        print('[warn] ComfyUI 输出区写入失败: %s' % _e, file=sys.stderr)
    try:
        r_out = Path(os.path.expanduser('~/videoGenerate-Model-zju/outputs'))
        r_out.mkdir(parents=True, exist_ok=True)
        r_dst = r_out / name
        _sh.copy2(str(out), str(r_dst))
        dest_candidates.append(str(r_dst))
    except Exception as _e:  # noqa: BLE001
        print('[warn] 仓库 outputs 写入失败: %s' % _e, file=sys.stderr)
    # §15d 会话产物目录（7860 页面结果区）：run_script 注入 VIDEOGEN_SESSION_CID → 页面预览/下载
    try:
        from h3 import session_outputs as _sess
        _cid = _sess.current_cid()
        if _cid:
            _sess_dst = _sess.place_output(Path(REPO), _cid, out, name=name)
            if _sess_dst:
                print('SESSION_OUT: logs/agent_chats/%s/outputs/%s（会话结果区，页面可预览/下载）'
                      % (_cid, _sess_dst.name), flush=True)
            else:
                print('[warn] 会话结果区写入失败（无会话上下文或 IO 异常）', file=sys.stderr)
        else:
            print('SESSION_OUT: (无会话上下文，跳过结果区)', flush=True)
    except Exception as _e:  # noqa: BLE001
        print('[warn] 会话结果区写入失败: %s' % _e, file=sys.stderr)
    # 面向用户输出脱敏（§15 边界）：只给文件名/相对说法，不给绝对路径
    if dest_candidates:
        print('COMFY_OUT: video/%s（ComfyUI 输出区，可预览/下载）' % Path(dest_candidates[0]).name, flush=True)
    if len(dest_candidates) > 1:
        print('REPO_OUT: outputs/%s（仓库 outputs，已同步 Windows）' % Path(dest_candidates[1]).name, flush=True)
    print('DONE_LIPSYNC_CHAIN', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
