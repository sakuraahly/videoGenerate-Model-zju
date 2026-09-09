#!/usr/bin/env python3
"""upscale_once — 对已有成品补跑 4x 超分（S13；ComfyUI ImageUpscaleWithModel 节点）。

背景：2026-09-08 夜 nt-hd-4x 系列在 ComfyUI 瞬时不可达时超分被跳过（主产物不受影响）；
本脚本对指定成品补跑：上传→队列→等待→取回→输出 <name>_upscale.mp4（4x）。

用法（spark）：python3 runs/h3/upscale_once.py --video outputs/video_463.mp4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'runs'))


def main() -> int:
    ap = argparse.ArgumentParser('4x 超分补跑')
    ap.add_argument('--video', required=True, help='成品路径（相对仓库或绝对）')
    ap.add_argument('--timeout', type=int, default=3600)
    args = ap.parse_args()
    src = Path(args.video)
    if not src.is_file():
        src = PROJECT_ROOT / src
    if not src.is_file():
        print('[错误] 视频不存在: %s' % src, file=sys.stderr)
        return 3
    import argparse as _a
    from h3_submit import _run_upscale
    from h3 import comfy as _c
    client = _c.ComfyClient(retries=2, request_timeout=8)
    na = _a.Namespace(upscale='4x')
    out = _run_upscale(PROJECT_ROOT, client, src, na)
    if out and Path(out).is_file():
        print('UPSCALE_OUT: outputs/%s（4x 超分补跑完成）' % Path(out).name, flush=True)
        return 0
    print('[错误] 超分产物缺失（检查 ComfyUI 可达性/日志）', file=sys.stderr)
    return 7


if __name__ == '__main__':
    sys.exit(main())
