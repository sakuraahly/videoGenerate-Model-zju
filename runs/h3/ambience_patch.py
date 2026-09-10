#!/usr/bin/env python3
"""ambience_patch — 给已成片补一层听得见的房间底噪（修历史 bug 用；新片直接走 film_stitch 即可）。

背景（2026-09-10 用户反馈）：成片**开头几秒没有声音**。实测定位：film_stitch 的底噪把目标电平
当成衰减量用了（brown 噪声源实测 RMS=-20dB，再压 -30dB → -50dB 以下），于是"垫了底噪"的段落
实际上还是静音。代码已修（按目标 RMS 反算增益），但**已生成的成片**（分段源文件已被后续任务覆盖、
无法重拼）用本工具直接补齐：
  · 全片铺一层 -38dB 的底噪（空气感，几乎不抢戏）；
  · 开头 N 秒再叠一层 -30dB（解决"开头静音/像多余片段"的观感）。

用法：
  python3 runs/h3/ambience_patch.py --video in.mp4 --out out.mp4 [--open-seconds 4.5]
      [--bed-db -38] [--open-db -30] [--kind room|rain]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 噪声源实测 RMS（与 film_stitch 同口径）
SOURCE_RMS = {'room': -27.4, 'rain': -25.1}   # room=粉噪 100–4000Hz 实测


def _dur(path: Path) -> float:
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                       capture_output=True, text=True, timeout=60)
    return float((r.stdout or '0').strip() or 0)


def _bed(kind: str, target_db: float, dur: float) -> str:
    src = SOURCE_RMS.get('rain' if kind == 'rain' else 'room', -20.0)
    gain = float(target_db) - src
    if kind == 'rain':
        return ('anoisesrc=color=pink:amplitude=0.5:sample_rate=48000:duration=%.3f,'
                'highpass=f=400,lowpass=f=9000,volume=%.1fdB,aformat=channel_layouts=stereo'
                % (dur, gain))
    return ('anoisesrc=color=pink:amplitude=0.35:sample_rate=48000:duration=%.3f,'
            'highpass=f=100,lowpass=f=4000,volume=%.1fdB,aformat=channel_layouts=stereo'
            % (dur, gain))


def patch(video: Path, out: Path, open_seconds: float, bed_db: float, open_db: float,
          kind: str) -> Path:
    d = _dur(video)
    if d <= 0:
        raise ValueError('读不到时长: %s' % video)
    cmd = ['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(video),
           '-f', 'lavfi', '-i', _bed(kind, bed_db, d)]
    have_open = open_seconds > 0
    if have_open:
        cmd += ['-f', 'lavfi', '-i', _bed(kind, open_db, open_seconds)]
    # 注意：loudnorm 不能排在 amix 之前（会把时间轴截短 3 秒，历史 bug）→ 这里只做等权混音
    fc = ('[0:a]highpass=f=60[a0];[a0][1:a]' + ('[2:a]' if have_open else '') +
          'amix=inputs=%d:duration=first:dropout_transition=0:normalize=0[a]' % (3 if have_open else 2))
    cmd += ['-filter_complex', fc, '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-ar', '48000', str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not Path(out).is_file():
        raise ValueError('底噪补齐失败: ' + (r.stderr or '')[-300:])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('给成片补房间底噪（成品后处理）')
    ap.add_argument('--video', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--open-seconds', type=float, default=4.5, help='开头加强底噪的秒数')
    ap.add_argument('--bed-db', type=float, default=-38.0, help='全片底噪目标 RMS')
    ap.add_argument('--open-db', type=float, default=-30.0, help='开头段底噪目标 RMS')
    ap.add_argument('--kind', default='room', choices=['room', 'rain'])
    a = ap.parse_args(argv)
    try:
        patch(Path(a.video), Path(a.out), a.open_seconds, a.bed_db, a.open_db, a.kind)
    except Exception as e:  # noqa: BLE001
        print('AMBIENCE_PATCH_ERROR: %s' % str(e)[:300])
        return 1
    print('AMBIENCE_PATCH_OK: %s（全片 %.1fdB / 开头 %.1fs 加强到 %.1fdB）'
          % (a.out, a.bed_db, a.open_seconds, a.open_db))
    return 0


if __name__ == '__main__':
    sys.exit(main())
