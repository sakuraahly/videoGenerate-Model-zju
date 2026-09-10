#!/usr/bin/env python3
"""film_stitch — 多段成片拼接（项目程序；agent run_script 可调）。

与 film_series.py 配套：把逐段产物按顺序拼接为一部成片：
  1) 每段归一化（同一分辨率/帧率/编码/双声道 44100）——跨源 aac 参数不一致时 concat 会
     失败（2026-09-09 现场：H3 原生音频流参数各异 → "channel element 2.5 is not allocated"）；
  2) demuxer concat（-c copy 零重编码）；输出 + PROBE 行（时长/宽高/帧率）。

用法（spark，agent run_script 亦同）：
  python3 runs/h3/film_stitch.py --segments f1.mp4,f2.mp4,... [--out /tmp/film.mp4]
      [--width 864 --height 480 --fps 24] [--keep-norm]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = 'ffmpeg'


def _run(cmd, timeout=1800):
    # -nostdin（2026-09-09）：ssh/无 tty 场景下 ffmpeg 会进入交互命令模式等待 stdin 而挂死
    # （症状：'Enter command: <target>|all <time> -1 <command>' 停驻，CPU 100% 无产出）
    if str(cmd[0]).find('ffmpeg') >= 0 and '-nostdin' not in cmd:
        cmd = cmd[:1] + ['-nostdin'] + cmd[1:]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError('fail: ' + ((r.stderr or r.stdout) or '')[-500:])
    return r


# 台词段（保留原生/人声音轨的段）走"语音清晰链"：提临场度 + 去浑浊 + 统一响度
# （2026-09-10 用户要求"想办法增加 H3 原生生成语音的清晰度"；实测原生 85%rolloff 仅 1664Hz）
SPEECH_CLARITY_AF_STITCH = ('highpass=f=75,equalizer=f=280:t=q:w=1.0:g=-1.5,'
                            'equalizer=f=3000:t=q:w=1.2:g=3.2,equalizer=f=6500:t=q:w=1.0:g=2.0,'
                            'loudnorm=I=-15:TP=-1.5:LRA=11')


def _probe_wh(path: Path) -> tuple:
    """读第一段的真实宽高（拼接默认沿用，避免把高分辨率段降采样）。"""
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(path)],
                           capture_output=True, text=True, timeout=60)
        w, h = (r.stdout or '').strip().split(',')[:2]
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return 0, 0


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                           capture_output=True, text=True, timeout=60)
        return float((r.stdout or '0').strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


# 噪声源实测 RMS（2026-09-10 标定）：底噪电平按"目标 RMS"反算增益，不再直接当衰减量用
# （历史 bug：把 -30 当 attenuation 用 → brown 源 -20dB 再压 30dB = -50dB，成片开头 4 秒等于静音）
# 2026-09-10 二次修正：原来的"房间底噪"= 布朗噪声低通 900Hz，能量几乎全在 900Hz 以下，
# 笔记本/手机喇叭放不出来 → 用户仍反馈"开头没声音"。改为**中频段房间空气声**（粉噪 100–4000Hz）。
AMBIENCE_SOURCE_RMS = {'room': -27.4, 'rain': -25.1}   # 实测（room=粉噪 100–4000Hz）
AMBIENCE_TARGET_DB = -30.0        # 无台词段（原本纯静音）的目标 RMS：明显可闻
AMBIENCE_UNDER_SPEECH_DB = -36.0  # 台词段垫底噪的目标 RMS：比台词低约 16dB


def ambience_source(kind: str, db: float, dur: float) -> str:
    """无台词段的"房间底噪/雨声"声源（lavfi 表达式）。

    背景（2026-09-10 用户定案）：H3 原生音轨是无台词镜头里的乱语人声（实测 seg0 = "笑得啊"），
    必须剔除；但整段静音（-91dB）会让成片"死气沉沉"。用户选择：**铺一层极轻的房间底噪**。
      room = 粉噪 100–4000Hz：室内空气声（中频段，中小喇叭也能听到；默认）
      rain = 粉红噪声 + 400Hz~9kHz 带通 + 轻颤音：像窗外雨声
    电平默认 -32dB（远低于语音，绝不抢戏），首尾各加淡入淡出防爆音。
    """
    k = str(kind or 'none').strip().lower()
    if k in ('', 'none', 'off'):
        return ''
    d = max(float(dur or 0), 1.0)
    fo = max(d - 1.2, 0.1)
    src_rms = AMBIENCE_SOURCE_RMS.get('rain' if k == 'rain' else 'room', -20.0)
    gain = float(db) - src_rms        # 目标 RMS → 相对源增益
    if k == 'rain':
        base = 'anoisesrc=color=pink:amplitude=0.5:sample_rate=48000'
        chain = 'highpass=f=400,lowpass=f=9000,tremolo=f=0.4:d=0.15'
    else:  # room
        base = 'anoisesrc=color=pink:amplitude=0.35:sample_rate=48000'
        chain = 'highpass=f=100,lowpass=f=4000'
    return (f'{base}:duration={d:.3f},{chain},volume={gain:.1f}dB,'
            f'afade=t=in:st=0:d=0.8,afade=t=out:st={fo:.3f}:d=1.2,aformat=channel_layouts=stereo')


def mix_filtergraph(width: int, height: int, fps: int) -> str:
    """台词段"原声 + 房间底噪"混音滤镜图。

    ⚠️ 顺序是回归修复点（2026-09-10 实测 bug）：loudnorm 放在 amix **之前**时，它内部的 3 秒
    前瞻缓冲会让 amix 的时间轴错位，输出音轨被截短（实测 7.29s→4.30s，成片尾部整段没声音，
    视频 19.08s / 音轨 16.08s）。正确顺序 = highpass → amix → asetpts(重置时间戳) → loudnorm。
    """
    return (f'[0:v]scale={width}:{height},fps={fps},format=yuv420p[v];'
            f'[0:a]highpass=f=75[a0];'
            f'[a0][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[am];'
            f'[am]asetpts=N/SR/TB,{SPEECH_CLARITY_AF_STITCH}[a]')


def normalize(src: Path, dst: Path, width: int, height: int, fps: int, strip_audio: bool = False,
              ambience: str = 'none', ambience_db: float = -32.0,
              mix_ambience: bool = False, enhance_speech: bool = False,
              ambience_speech_db: float = None) -> None:
    vopts = ['-c:v', 'libx264', '-crf', '21', '-preset', 'fast', '-pix_fmt', 'yuv420p']
    aopts = ['-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-ar', '48000']
    dur = _probe_duration(src)
    if strip_audio:
        # 2026-09-09 修复：不能 -an（concat demuxer 要求全部输入流一致，缺音轨会把 keep 段的音轨一起丢）
        # → 垫同参数音轨；2026-09-10：默认垫"房间底噪"而非纯静音（用户定案：房间底噪最自然）
        amb = ambience_source(ambience, ambience_db, dur)
        asrc = amb if amb else 'anullsrc=r=48000:cl=stereo'
        cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(src),
               '-f', 'lavfi', '-t', '999', '-i', asrc,
               '-map', '0:v:0', '-map', '1:a:0', '-shortest'] + aopts + [
               '-vf', f'scale={width}:{height}', '-r', str(fps)] + vopts
    elif mix_ambience and ambience not in ('', 'none'):
        # 台词段也垫同一条底噪（混音而非替换）——否则"有底噪的段"与"干声台词段"之间会
        # 听出明显的真空/切换（2026-09-10 自检发现）
        amb = ambience_source(ambience, (ambience_speech_db if ambience_speech_db is not None
                                         else ambience_db), dur)
        fc = mix_filtergraph(width, height, fps)
        cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(src),
               '-f', 'lavfi', '-t', f'{max(dur, 1.0):.3f}', '-i', amb,
               '-filter_complex', fc, '-map', '[v]', '-map', '[a]'] + vopts + aopts
    else:
        # 2026-09-10：逐段响度对齐 + 统一 48k 立体声（跨段音量忽大忽小=用户听感"听不清"）
        cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(src),
               '-vf', f'scale={width}:{height}', '-r', str(fps)] + vopts + [
               '-af', (SPEECH_CLARITY_AF_STITCH if enhance_speech
                       else 'highpass=f=60,loudnorm=I=-15:TP=-1.5:LRA=11')] + aopts
    cmd.append(str(dst))
    _run(cmd)
    return


def stitch(segments: list, out: Path, width: int = 0, height: int = 0,
           fps: int = 24, keep_norm: bool = False, strip_audio: bool = False,
           keep_segs: set | None = None, ambience: str = 'room',
           ambience_db: float = AMBIENCE_TARGET_DB, mix_ambience: bool = False,
           ambience_speech_db: float = AMBIENCE_UNDER_SPEECH_DB) -> Path:
    keep_segs = keep_segs or set()
    # 2026-09-10 实测 bug 修复：默认尺寸过去写死 864×480，会把 720p/1080p 分段**降采样**成 480p
    # （用户要 720p 版时成片仍是 480p）。现在 width/height=0 表示"跟随第一段真实分辨率"。
    if not width or not height:
        w0, h0 = _probe_wh(Path(segments[0]))
        width = width or w0 or 864
        height = height or h0 or 480
    work = Path(tempfile.mkdtemp(prefix='film_stitch_'))
    try:
        norm_paths = []
        for i, seg in enumerate(segments):
            sp = Path(seg)
            if not sp.is_file():
                raise RuntimeError(f'段文件不存在: {seg}')
            np_ = work / f'n{i:02d}.mp4'
            _keep = str(i) in keep_segs
            normalize(sp, np_, width, height, fps, strip_audio=(strip_audio and not _keep),
                      ambience=ambience, ambience_db=ambience_db,
                      mix_ambience=(mix_ambience and _keep), enhance_speech=_keep,
                      ambience_speech_db=ambience_speech_db)
            norm_paths.append(np_)
        lst = work / 'list.txt'
        lst.write_text(chr(10).join(f"file '{p}'" for p in norm_paths) + chr(10), encoding='utf-8')
        out.parent.mkdir(parents=True, exist_ok=True)
        # concat 一律重编码（2026-09-09 用户'拼接错乱'根因：-c copy 对参数/时间戳
        # 不一致的段流（ComfyUI 直出 vs 台词链重编）会花屏/跳帧/重影；重编码保证单一致流）
        _run([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
              '-i', str(lst), '-c:v', 'libx264', '-crf', '21', '-preset', 'fast',
              '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', str(out)])
        return out
    finally:
        if keep_norm:
            print(f'NORM_DIR: {work}', flush=True)
        else:
            shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser('多段成片拼接')
    ap.add_argument('--segments', required=True, help='逗号分隔的段文件路径（按顺序）')
    ap.add_argument('--out', default='/tmp/film_stitched.mp4')
    ap.add_argument('--width', type=int, default=0, help='默认 0=跟随第一段分辨率（不再写死 480p）')
    ap.add_argument('--height', type=int, default=0, help='默认 0=跟随第一段分辨率')
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--keep-norm', action='store_true')
    ap.add_argument('--strip-audio', action='store_true', help='剔除各段原生音轨（H3 伪语音=乱码级）')
    ap.add_argument('--keep-audio-segs', default='', help='逗号分隔段索引（0 基）——strip-audio 时仍保留音轨（如真台词段）')
    ap.add_argument('--ambience', default='room', choices=['room', 'rain', 'none'],
                    help='被剔除音轨的段铺什么底噪：room=房间底噪(默认,最自然)/rain=雨声/none=纯静音')
    ap.add_argument('--ambience-db', type=float, default=-33.0,
                    help='无台词段底噪的目标 RMS（默认 -33dB；比台词低约 13dB，明显可闻）')
    ap.add_argument('--ambience-speech-db', type=float, default=-38.0,
                    help='台词段垫底噪的目标 RMS（默认 -38dB，比台词低约 18dB）')
    ap.add_argument('--ambience-under-speech', action='store_true',
                    help='台词段也垫同一条底噪（混音）——避免"有底噪的段"与"干声段"之间听出真空')
    args = ap.parse_args()
    segs = [s.strip() for s in args.segments.split(',') if s.strip()]
    keep_segs = {s.strip() for s in args.keep_audio_segs.split(',') if s.strip()}
    out = Path(args.out)
    stitch(segs, out, args.width, args.height, args.fps, args.keep_norm, args.strip_audio, keep_segs,
           ambience=args.ambience, ambience_db=args.ambience_db,
           mix_ambience=args.ambience_under_speech,
           ambience_speech_db=args.ambience_speech_db)
    _p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                         '-show_entries', 'stream=width,height,r_frame_rate',
                         '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1', str(out)],
                        capture_output=True, text=True, timeout=60)
    print(f'STITCH_OUT: {out.name}（{len(segs)} 段拼接成片）', flush=True)
    print('PROBE: ' + ' '.join(_p.stdout.splitlines()), flush=True)
    print('DONE_STITCH', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
