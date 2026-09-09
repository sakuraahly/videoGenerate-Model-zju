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
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError('fail: ' + ((r.stderr or r.stdout) or '')[-500:])
    return r


def normalize(src: Path, dst: Path, width: int, height: int, fps: int, strip_audio: bool = False) -> None:
    cmd = [FFMPEG, '-y', '-v', 'error', '-i', str(src),
           '-vf', f'scale={width}:{height}', '-r', str(fps),
           '-c:v', 'libx264', '-crf', '21', '-preset', 'fast',
           '-pix_fmt', 'yuv420p']
    if strip_audio:
        cmd.append('-an')
    else:
        cmd += ['-c:a', 'aac', '-ac', '2', '-ar', '44100']
    cmd.append(str(dst))
    _run(cmd)


def stitch(segments: list, out: Path, width: int = 864, height: int = 480,
           fps: int = 24, keep_norm: bool = False, strip_audio: bool = False) -> Path:
    work = Path(tempfile.mkdtemp(prefix='film_stitch_'))
    try:
        norm_paths = []
        for i, seg in enumerate(segments):
            sp = Path(seg)
            if not sp.is_file():
                raise RuntimeError(f'段文件不存在: {seg}')
            np_ = work / f'n{i:02d}.mp4'
            normalize(sp, np_, width, height, fps, strip_audio=strip_audio)
            norm_paths.append(np_)
        lst = work / 'list.txt'
        lst.write_text(chr(10).join(f"file '{p}'" for p in norm_paths) + chr(10), encoding='utf-8')
        out.parent.mkdir(parents=True, exist_ok=True)
        _run([FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
              '-i', str(lst), '-c', 'copy', str(out)])
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
    args = ap.parse_args()
    segs = [s.strip() for s in args.segments.split(',') if s.strip()]
    out = Path(args.out)
    stitch(segs, out, args.width, args.height, args.fps, args.keep_norm, args.strip_audio)
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
