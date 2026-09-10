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


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                           capture_output=True, text=True, timeout=60)
        return float((r.stdout or '0').strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def ambience_source(kind: str, db: float, dur: float) -> str:
    """无台词段的"房间底噪/雨声"声源（lavfi 表达式）。

    背景（2026-09-10 用户定案）：H3 原生音轨是无台词镜头里的乱语人声（实测 seg0 = "笑得啊"），
    必须剔除；但整段静音（-91dB）会让成片"死气沉沉"。用户选择：**铺一层极轻的房间底噪**。
      room = 布朗噪声 + 低通 900Hz：像室内空调/远处街道的低频hush（最自然，默认）
      rain = 粉红噪声 + 400Hz~9kHz 带通 + 轻颤音：像窗外雨声
    电平默认 -32dB（远低于语音，绝不抢戏），首尾各加淡入淡出防爆音。
    """
    k = str(kind or 'none').strip().lower()
    if k in ('', 'none', 'off'):
        return ''
    d = max(float(dur or 0), 1.0)
    fo = max(d - 1.2, 0.1)
    if k == 'rain':
        base = 'anoisesrc=color=pink:amplitude=0.5:sample_rate=48000'
        chain = 'highpass=f=400,lowpass=f=9000,tremolo=f=0.4:d=0.15'
    else:  # room
        base = 'anoisesrc=color=brown:amplitude=0.6:sample_rate=48000'
        chain = 'highpass=f=50,lowpass=f=900'
    return (f'{base}:duration={d:.3f},{chain},volume={float(db):.1f}dB,'
            f'afade=t=in:st=0:d=0.8,afade=t=out:st={fo:.3f}:d=1.2,aformat=channel_layouts=stereo')


def normalize(src: Path, dst: Path, width: int, height: int, fps: int, strip_audio: bool = False,
              ambience: str = 'none', ambience_db: float = -32.0,
              mix_ambience: bool = False) -> None:
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
        amb = ambience_source(ambience, ambience_db, dur)
        fc = (f'[0:v]scale={width}:{height},fps={fps},format=yuv420p[v];'
              f'[0:a]highpass=f=60,loudnorm=I=-15:TP=-1.5:LRA=11[a0];'
              f'[a0][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]')
        cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(src),
               '-f', 'lavfi', '-t', f'{max(dur, 1.0):.3f}', '-i', amb,
               '-filter_complex', fc, '-map', '[v]', '-map', '[a]'] + vopts + aopts
    else:
        # 2026-09-10：逐段响度对齐 + 统一 48k 立体声（跨段音量忽大忽小=用户听感"听不清"）
        cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(src),
               '-vf', f'scale={width}:{height}', '-r', str(fps)] + vopts + [
               '-af', 'highpass=f=60,loudnorm=I=-15:TP=-1.5:LRA=11'] + aopts
    cmd.append(str(dst))
    _run(cmd)
    return


def stitch(segments: list, out: Path, width: int = 864, height: int = 480,
           fps: int = 24, keep_norm: bool = False, strip_audio: bool = False,
           keep_segs: set | None = None, ambience: str = 'room',
           ambience_db: float = -32.0, mix_ambience: bool = False) -> Path:
    keep_segs = keep_segs or set()
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
                      mix_ambience=(mix_ambience and _keep))
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
    ap.add_argument('--width', type=int, default=864)
    ap.add_argument('--height', type=int, default=480)
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--keep-norm', action='store_true')
    ap.add_argument('--strip-audio', action='store_true', help='剔除各段原生音轨（H3 伪语音=乱码级）')
    ap.add_argument('--keep-audio-segs', default='', help='逗号分隔段索引（0 基）——strip-audio 时仍保留音轨（如真台词段）')
    ap.add_argument('--ambience', default='room', choices=['room', 'rain', 'none'],
                    help='被剔除音轨的段铺什么底噪：room=房间底噪(默认,最自然)/rain=雨声/none=纯静音')
    ap.add_argument('--ambience-db', type=float, default=-30.0, help='底噪电平（默认 -30dB，远低于语音）')
    ap.add_argument('--ambience-under-speech', action='store_true',
                    help='台词段也垫同一条底噪（混音）——避免"有底噪的段"与"干声段"之间听出真空')
    args = ap.parse_args()
    segs = [s.strip() for s in args.segments.split(',') if s.strip()]
    keep_segs = {s.strip() for s in args.keep_audio_segs.split(',') if s.strip()}
    out = Path(args.out)
    stitch(segs, out, args.width, args.height, args.fps, args.keep_norm, args.strip_audio, keep_segs,
           ambience=args.ambience, ambience_db=args.ambience_db,
           mix_ambience=args.ambience_under_speech)
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
