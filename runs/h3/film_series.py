#!/usr/bin/env python3
"""film_series — 连贯多段短片生成（i2v 首帧继承链；项目程序，agent run_script 可调）。

设计（2026-09-09 用户批评'各自为战、连贯性一塌糊涂'后的工程化答案）：
  每段由**上一段的末帧作为本段首帧**（i2v 首帧继承）——场景/运镜/人物跨段延续，
  段间无缝（片段不再各自为战）；每段提示词统一附加"延续句"（同人物/同场景/同光照/慢速连续运动/无切）。
  首段：t2v（文生）或 --start-image（给定首帧图）。
  输出：逐段 segment_00.mp4... + 可选 --stitch 拼接成片（film_stitch.py）。

用法（spark）：
  python3 runs/h3/film_series.py --prompts-file config/xxx_prompts.json [--start-image first.png]
      [--resolution 480p --seconds 4 --seed 20260908 --stitch --out /tmp/film.mp4]
prompts-file：{"0": "...", "1": "...", ...}（段索引→提示词；长度即为段数）。
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
STITCH = PROJECT_ROOT / 'runs' / 'h3' / 'film_stitch.py'
CONTINUE_TAIL = (' The shot continues seamlessly from the previous frame; same characters, '
                 'same location, same lighting, same color grade; slow continuous motion, no cuts. '
                 'Realistic physical logic: natural human movement, believable weight and gravity, '
                 'plausible camera; NO written characters, no signage text, no readable letters, '
                 'no numbers anywhere in frame; no text, no watermark, no dialogue.')


def _run(cmd, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r


def _out_of(log: str) -> str:
    """从提交日志提取本段产物（REMOTE_VIDEO_PATH / LOCAL_OUTPUT）。"""
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


def main() -> int:
    ap = argparse.ArgumentParser('连贯多段短片（i2v 首帧继承）')
    ap.add_argument('--prompts-file', required=True, help='段提示词 JSON {"0":..., "1":...}')
    ap.add_argument('--start-image', default='', help='首帧图（有则段0 也走 i2v；缺省段0=t2v）')
    ap.add_argument('--resolution', default='480p')
    ap.add_argument('--lora', default='fl2v_4step',
                    help='加速档（fl2v_4step 快/物理弱；none=20 步全质=物理与细节最佳；fl2v_8step 居中）')
    ap.add_argument('--seconds', type=int, default=4)
    ap.add_argument('--seed', type=int, default=20260908)
    ap.add_argument('--work-dir', default='/tmp/film_series')
    ap.add_argument('--stitch', action='store_true', help='完成后拼接成片')
    ap.add_argument('--strip-audio', action='store_true',
                    help='拼接时剔除各段原生音轨（H3 伪语音=乱码级，用户听感差；真台词由 --voice-segment 补）')
    ap.add_argument('--voice-segment', type=int, default=-1, help='接真台词链的段索引（生成后本段用 lipsync_chain 版替换）')
    ap.add_argument('--line', default='', help='台词（--voice-segment 时必填）')
    ap.add_argument('--voice', default='yunxi')
    ap.add_argument('--out', default='/tmp/film_series.mp4')
    args = ap.parse_args()

    prompts = json.loads(Path(args.prompts_file).read_text(encoding='utf-8'))
    pidxs = sorted(prompts, key=lambda x: int(x))
    if not pidxs:
        print('[错误] prompts-file 为空', file=sys.stderr)
        return 3
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    segs_out = []
    prev_frame = Path(args.start_image) if args.start_image else None
    for k, idx in enumerate(pidxs):
        if prev_frame is not None and prev_frame.is_file():
            cmd = ['python3', str(SUBMIT), '--stage', 'i2v', '--resolution', args.resolution,
                   '--lora', args.lora,
                   '--seconds', str(args.seconds), '--seed', str(args.seed),
                   '--image', str(prev_frame),
                   '--prompt', str(prompts[idx]) + CONTINUE_TAIL]
        else:
            cmd = ['python3', str(SUBMIT), '--stage', 't2v', '--resolution', args.resolution,
                   '--lora', args.lora,
                   '--seconds', str(args.seconds), '--seed', str(args.seed),
                   '--prompt', str(prompts[idx])]
        print(f'== seg{idx} ({"i2v" if cmd[cmd.index("--stage")+1] == "i2v" else "t2v"})', flush=True)
        r = _run(cmd)
        log = (r.stdout or '') + (r.stderr or '')
        seg = _out_of(log)
        if not seg or not Path(seg).is_file():
            print(f'[错误] seg{idx} 产物未找到（rc={r.returncode}）', file=sys.stderr)
            print(log[-600:], file=sys.stderr)
            return 4
        segp = Path(seg)
        # 台词段（--voice-segment）：本段产完后用真台词链替换（H3 伪语音/无脸话=用户'无法解析'投诉根因）
        if int(idx) == args.voice_segment and args.line:
            chain_cmd = ['python3', str(PROJECT_ROOT / 'runs' / 'h3' / 'lipsync_chain.py'),
                         '--video', str(segp), '--line', args.line, '--voice', args.voice,
                         '--asr-check']
            rc = _run(chain_cmd)
            cl = (rc.stdout or '') + (rc.stderr or '')
            import re as _re
            m = _re.search(r'COMFY_OUT: video/(\S+?)（|FINAL: (\S+) ', cl)
            chain_path = ''
            for _l in cl.splitlines():
                if _l.startswith('COMFY_OUT:'):
                    chain_path = str(Path.home() / 'ai' / 'ComfyUI' / 'output' / 'video' /
                                     _l.split('video/')[1].split('（')[0])
                    break
            if chain_path and Path(chain_path).is_file():
                segp = Path(chain_path)
                print(f'seg{idx} 台词链版: {Path(chain_path).name}', flush=True)
            else:
                print(f'[warn] seg{idx} 台词链未成功（保留源段）', file=sys.stderr)
                print(cl[-400:], file=sys.stderr)
        # 保存段产物引用 + 取末帧作为下一段首帧
        segs_out.append(str(segp))
        lf = work / f'last_{idx}.png'
        if not _last_frame(segp, lf):
            print(f'[warn] seg{idx} 末帧提取失败', file=sys.stderr)
        else:
            prev_frame = lf
        print(f'seg{idx} OK: {segp.name}', flush=True)

    print('SEGMENTS: ' + ','.join(Path(s).name for s in segs_out), flush=True)
    if args.stitch:
        _st = ['python3', str(STITCH), '--segments', ','.join(segs_out), '--out', args.out]
        if args.strip_audio:
            _st.append('--strip-audio')
        r = _run(_st)
        print((r.stdout or r.stderr or '')[-400:], flush=True)
        if r.returncode != 0:
            print('[错误] 拼接失败', file=sys.stderr)
            return 5
    print('DONE_FILM_SERIES', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
