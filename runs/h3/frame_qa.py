#!/usr/bin/env python3
"""frame_qa — 用视觉模型验收"画面里有没有不该出现的字"（2026-09-10 建立）。

背景：H3 有相当概率把提示词里的台词**自己画成画面字幕**——加引号时几乎必画；改成
"去引号 + audio only / never appear as written text" 只能降低概率、**不能杜绝**（实测同一条
故事片两段仍各带一条模型字幕）。用户定案：字幕由后期烧录 → 画面里出现模型字幕即为缺陷。
提示词侧抑制不可靠，故本工具用视觉模型做**硬闸门**：抽帧 → 问 "有没有字幕/文字" → 判定。

用法（spark 上）：
  MS_TOKEN=xxx python3 runs/h3/frame_qa.py <video> [--times 2,4,6] [--band 0.55,1.0]
      [--question "..."] [--model Qwen/Qwen3-VL-8B-Instruct]
输出：
  QA_FRAME: t=2.0 YES 还能听见当年的声音吗
  QA_RESULT: TEXT | CLEAN | UNKNOWN       # UNKNOWN=缺 token/网络失败（绝不做假判定）
退出码：0=CLEAN, 3=TEXT, 2=UNKNOWN
环境：MS_TOKEN 或 LLM_API_KEY（魔搭访问令牌）；MS_VLM_MODEL / MS_API_BASE 可覆盖。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

DEFAULT_MODEL = 'Qwen/Qwen3-VL-8B-Instruct'
DEFAULT_BASE = 'https://api-inference.modelscope.cn/v1'
DEFAULT_Q = ('Does this image contain any on-screen subtitle, caption, karaoke lyric or lettering '
             'overlaid on the picture? Answer strictly YES or NO, then quote the text if yes.')


def token() -> str:
    return (os.environ.get('MS_TOKEN') or os.environ.get('LLM_API_KEY') or '').strip()


def grab_frame(video: str, t: float, band: tuple, out: str) -> bool:
    y0, y1 = band
    vf = 'crop=iw:ih*%.3f:0:ih*%.3f,scale=768:-1' % (y1 - y0, y0)
    r = subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-ss', '%.2f' % t, '-i', video,
                        '-frames:v', '1', '-vf', vf, out], capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and Path(out).is_file()


def ask_vlm(path: str, question: str, model: str, base: str, tok: str,
            attempts: int = 3) -> str:
    """问视觉模型；429（免费额度限流）自动退避重试——实测连发多帧会撞限流。"""
    last = None
    for i in range(max(1, attempts)):
        try:
            return _ask_once(path, question, model, base, tok)
        except urllib.error.HTTPError as e:      # noqa: F821
            last = e
            if e.code not in (429, 500, 502, 503):
                raise
            time.sleep(3.0 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last if last else RuntimeError('ask_vlm failed')


def _ask_once(path: str, question: str, model: str, base: str, tok: str) -> str:
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    body = {'model': model, 'temperature': 0, 'max_tokens': 64,
            'messages': [{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
                {'type': 'text', 'text': question}]}]}
    req = urllib.request.Request(base.rstrip('/') + '/chat/completions',
                                 data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + tok})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode('utf-8', 'replace'))
    return str(((d.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()


def check(video: str, times: list, band: tuple, question: str, model: str, base: str,
          tok: str) -> tuple:
    """返回 (verdict, rows)。verdict ∈ {'clean','text','unknown'}"""
    if not tok:
        return 'unknown', [('no-token', 'MS_TOKEN/LLM_API_KEY 未设置')]
    rows, seen_text, unknown = [], 0, 0
    tmp = tempfile.mkdtemp(prefix='frame_qa_')
    for t in times:
        f = str(Path(tmp) / ('f_%.2f.jpg' % t))
        if not grab_frame(video, t, band, f):
            unknown += 1
            rows.append((t, 'UNKNOWN', '抽帧失败'))
            continue
        try:
            ans = ask_vlm(f, question, model, base, tok)
        except Exception as e:  # noqa: BLE001
            unknown += 1
            rows.append((t, 'UNKNOWN', str(e)[:100]))
            continue
        yes = ans.strip().upper().startswith('YES')
        rows.append((t, 'YES' if yes else 'NO', ans.replace(chr(10), ' ')[:80]))
        seen_text += 1 if yes else 0
    if seen_text:
        return 'text', rows
    if unknown and not any(r[1] == 'NO' for r in rows):
        return 'unknown', rows
    return 'clean', rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('画面文字验收（视觉模型）')
    ap.add_argument('video')
    ap.add_argument('--times', default='2,4,6', help='抽帧时间点（秒，逗号分隔）')
    ap.add_argument('--band', default='0.55,1.0', help='检查区域（画面高度比例 y0,y1）')
    ap.add_argument('--question', default=DEFAULT_Q)
    ap.add_argument('--model', default=os.environ.get('MS_VLM_MODEL') or DEFAULT_MODEL)
    ap.add_argument('--base', default=os.environ.get('MS_API_BASE') or DEFAULT_BASE)
    a = ap.parse_args(argv)
    times = [float(x) for x in str(a.times).split(',') if x.strip()]
    band = tuple(float(x) for x in str(a.band).split(','))
    verdict, rows = check(a.video, times, band, a.question, a.model, a.base, token())
    for t, v, note in rows:
        print('QA_FRAME: t=%s %s %s' % (t, v, note), flush=True)
    print('QA_RESULT: ' + verdict.upper(), flush=True)
    return 0 if verdict == 'clean' else (3 if verdict == 'text' else 2)


if __name__ == '__main__':
    sys.exit(main())
