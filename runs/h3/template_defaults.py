#!/usr/bin/env python3
"""template_defaults — 把"语音清晰条款"写进 ComfyUI 工作流模板的默认提示词里（幂等）。

背景（2026-09-10 用户要求）："能不能把相关的提示词直接写在 ComfyUI 工作流的默认设置里面"。
过去语音约束只存在于 agent 临场写的提示词里；漏写就会出现含糊人声/乱语人声。
本工具把条款固化到模板默认值，三处一起生效：
  1) config/templates/*.json 的默认提示词部件（在 ComfyUI 里打开模板即可见）；
  2) prompts/positive_prompts.txt / negative_prompts.txt（工作流默认提示词文件）；
  3) runs/h3_submit.py 提交时注入（任何来源的提示词都带上，--no-speech-clause 可关）。

用法：
  python3 runs/h3/template_defaults.py --check     # 只看有没有
  python3 runs/h3/template_defaults.py --apply     # 写入（幂等）
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3.prompts import SPEECH_POS  # noqa: E402

TEMPLATE_DIR = ROOT / 'config' / 'templates'
# 模板里承载"默认提示词"的节点类型（实测三套模板各异）：
#   t2v/i2v = 子图节点 widgets_values[0]；r2v = PrimitiveStringMultiline
PROMPT_NODE_TYPES = ('PrimitiveStringMultiline',)
_SUBGRAPH_PROMPT_WIDGET = 0


def _iter_prompt_slots(doc: dict):
    """产出 (可写回调, 当前文本) —— 覆盖子图节点与 PrimitiveStringMultiline。"""
    for node in (doc.get('nodes') or []):
        t = str(node.get('type') or '')
        wv = node.get('widgets_values')
        if not isinstance(wv, list) or not wv:
            continue
        if t in PROMPT_NODE_TYPES and isinstance(wv[0], str):
            yield node, wv, 0
        elif len(t) == 36 and isinstance(wv[0], str) and len(wv[0]) > 120:
            # 子图节点：widgets_values[0] 即默认提示词（其余是模型文件名）
            yield node, wv, _SUBGRAPH_PROMPT_WIDGET


def patch_file(path: Path, apply: bool = False) -> dict:
    doc = json.load(io.open(path, encoding='utf-8-sig'))
    touched, already = 0, 0
    for _node, wv, idx in _iter_prompt_slots(doc):
        text = wv[idx]
        if 'clear articulate speech' in text.lower():
            already += 1
            continue
        if apply:
            wv[idx] = text.rstrip().rstrip(',') + ', ' + SPEECH_POS
        touched += 1
    if apply and touched:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'file': path.name, 'patched': touched, 'already': already}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('把语音条款写进工作流模板默认提示词')
    ap.add_argument('--apply', action='store_true', help='写入（默认只检查）')
    ap.add_argument('--check', action='store_true', help='只检查是否已写入（默认行为，保留以便脚本化调用）')
    ap.add_argument('--dir', default=str(TEMPLATE_DIR))
    a = ap.parse_args(argv)
    total = 0
    for f in sorted(Path(a.dir).glob('video_minimax_h3_*.json')):
        r = patch_file(f, apply=a.apply)
        total += r['patched']
        print('%-34s 待写=%d 已有=%d' % (r['file'], r['patched'], r['already']))
    print(('APPLIED' if a.apply else 'CHECK_ONLY') + ': 共 %d 处' % total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
