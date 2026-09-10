#!/usr/bin/env python3
"""comfy_finalize — 100% ComfyUI 队列内成品链（H3Finalize + H3AsrCheck 节点）。

定位（2026-09-09 用户要求"我要 100% 队列版本"）：
  生成完成后，**配音/字幕/音轨替换/ASR 全部在 ComfyUI 队列内由自定义节点执行**
  （custom_nodes/h3_finalize：H3Finalize 节点内子进程调用 tts-venv 本地合成；
  本地不再做任何 ffmpeg 后处理）。本脚本只负责"提交 + 轮询 + 回报"。

用法（spark）：
  python3 runs/h3/comfy_finalize.py --video outputs/video_XXX.mp4 \
      --text "台词文本" [--voice yunxi] [--style harmony] [--timeout 1800]

关键参数（踩坑记录 2026-09-09）：
  · audio_mode 必须显式 'replace'（节点默认 'keep'＝保留原轨=H3 伪语音乱码；
    用户反馈"ComfyUI 直出的还是错误语音"即此因）；
  · 节点内 TTS 强制 CPU（子进程 CUDA 会与 ComfyUI 抢 GPU 而挂起）；
  · /tmp 下不得残留同标准库名脚本（如 bisect.py 曾导致 import 时死锁+ffmpeg 卡死）。
产物：<video 同名>_final.mp4（+ .srt 字幕，与输入同目录），ASR 分数由 H3AsrCheck 节点输出。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h3.comfy import ComfyClient  # noqa: E402


def submit_and_wait(comfy_url: str, video: str, text: str, voice: str = 'yunxi',
                    style: str = 'harmony', timeout: int = 1800) -> dict:
    wf = {
        '1': {'class_type': 'H3Finalize', 'inputs': {
            'video': str(video), 'text': text, 'voice': voice,
            'audio_mode': 'replace',      # 必须 replace（keep=保留伪语音）
            'subtitle_source': 'text',    # 字幕=台词原文（不用 ASR 转录）
            'backend': 'cosy',
            'subtitle_style': style}},
        '2': {'class_type': 'H3AsrCheck', 'inputs': {
            'media': ['1', 0], 'text_compare': text}},
    }
    req = urllib.request.Request(comfy_url.rstrip('/') + '/prompt',
                                 data=json.dumps({'prompt': wf, 'client_id': 'h3finalize'}).encode(),
                                 headers={'Content-Type': 'application/json'})
    pid = json.load(urllib.request.urlopen(req, timeout=60))['prompt_id']
    print('PROMPT_ID: %s' % pid, flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(8)
        try:
            h = json.load(urllib.request.urlopen(
                comfy_url.rstrip('/') + '/history/' + pid, timeout=20))
        except Exception:  # noqa: BLE001
            continue
        if pid in h:
            st = (h[pid].get('status') or {}).get('status_str', '?')
            print('STATUS: %s' % st, flush=True)
            return h[pid]
    print('TIMEOUT after %ds（任务可能仍在队列，稍后重查 history）' % timeout, flush=True)
    return {}


def main() -> int:
    ap = argparse.ArgumentParser('队列内成品链（H3Finalize + H3AsrCheck）')
    ap.add_argument('--video', required=True, help='生成产物路径（ComfyUI 直出 mp4）')
    ap.add_argument('--text', required=True, help='台词（字幕=原文；TTS 文本）')
    ap.add_argument('--voice', default='yunxi', choices=['xiaoxiao', 'yunxi', 'aria', 'daler'])
    ap.add_argument('--style', default='harmony')
    ap.add_argument('--comfy-url', default='http://127.0.0.1:8188')
    ap.add_argument('--timeout', type=int, default=1800)
    args = ap.parse_args()
    src = Path(args.video)
    if not src.is_file():
        # 兼容 outputs/video_x.mp4 相对路径
        alt = Path(__file__).resolve().parent.parent.parent / args.video
        if alt.is_file():
            src = alt
        else:
            print('[错误] 视频不存在: %s' % args.video, file=sys.stderr)
            return 3
    submit_and_wait(args.comfy_url, str(src), args.text, args.voice, args.style, args.timeout)
    out = src.with_name(src.stem + '_final.mp4')
    print('FINAL: %s (%s)' % (out, '存在' if out.is_file() else '缺失'))
    print('SRT: %s' % src.with_name(src.stem + '_final.srt'))
    return 0 if out.is_file() else 4


if __name__ == '__main__':
    sys.exit(main())
