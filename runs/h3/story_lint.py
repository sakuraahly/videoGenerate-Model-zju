#!/usr/bin/env python3
"""story_lint — 剧本 JSON 预检（生成之前就把坑挡住；agent 写剧本后必须先跑这个）。

为什么需要（2026-09-10 用户要求「训练 agent 根据用户输入写剧本和提示词的本事」）：
故事片的坑几乎都出在"文本层"，一旦开跑就是几分钟 GPU 白烧：
  · 台词用引号写进 prompt → H3 会**把台词画成画面字幕**（实测几乎必画），成片就变成两条叠字；
  · 台词没写 speaker 而本镜头有多个角色 → 不知道谁在说；
  · cast 里写了 characters 里没有的人 → 人物形象卡注入失败，脸会漂；
  · 台词太长而 seconds 太小 → 话说一半画面就结束（用户历史批评）；
  · style 里同时要字又不要字 → 自相矛盾。
本工具把这些做成 0 成本的静态检查，agent 生成前先跑，报错就别开跑。

用法：
  python3 runs/h3/story_lint.py config/story_xxx.json
  → 逐条打印 LINT_ERROR / LINT_WARN，末尾 LINT_SUMMARY: errors=N warnings=M
退出码：0=无错误（可有告警）, 1=有错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 台词秒数估算（与 story_film 一致：0.36s/字 + 1s 余量）
SEC_PER_CHAR = 0.36
_QUOTE_RE = re.compile(r'[\u201c\u201d"\u300c\u300d\u300e\u300f]')


def _iter_lines(story: dict):
    for k, v in (story.get('lines') or {}).items():
        yield str(k), (v or {})


def lint(story: dict) -> tuple:
    """返回 (errors, warnings) —— 都是 '位置: 说明' 字符串列表。"""
    err, warn = [], []

    if not str(story.get('title') or '').strip():
        err.append('story: 缺 title')
    segs = story.get('segments') or []
    if not isinstance(segs, list) or not segs:
        err.append('story: segments 必须是非空数组')
        return err, warn
    chars = story.get('characters') or {}
    if not chars:
        warn.append('story: 没有 characters 角色卡 → 跨镜头人物形象容易漂')
    base_sec = int(story.get('seconds') or 4)

    for i, seg in enumerate(segs):
        p = str((seg or {}).get('prompt') or '')
        if not p.strip():
            err.append('seg%d: prompt 为空' % i)
        # 1) 引号 = H3 画字幕的触发开关（实测）
        if _QUOTE_RE.search(p):
            err.append('seg%d: prompt 里出现引号 → H3 会把这句话画成画面字幕（字幕由后期加, 必须去掉引号）' % i)
        # 2) cast 必须是角色卡里的名字
        for c in ((seg or {}).get('cast') or []):
            if c not in chars:
                err.append('seg%d: cast 里的 %r 不在 characters 中' % (i, c))
        # 3) 单镜头单动作（粗判：太多 then/并且 说明需要拆段）
        if len(re.findall(r'\bthen\b|然后|接着|随后', p, re.I)) >= 3:
            warn.append('seg%d: 一个镜头里动作太多（then/然后 ≥3）→ 建议拆段' % i)
        if len(p) > 1600:
            warn.append('seg%d: prompt 过长（%d 字符）→ 模型容易漏动作' % (i, len(p)))
        # 4) style 与 prompt 自相矛盾：本镜头要画面文字，整体却禁字
        if re.search(r'sign reads|招牌上写着|字样是', p, re.I) \
           and re.search(r'no (on-screen )?(text|lettering|subtitles)', str(story.get('style') or ''), re.I):
            warn.append('seg%d: 本镜头要画面文字，但 style 里禁字 → 自相矛盾, 二选一' % i)

    style = str(story.get('style') or '')
    for k, line in _iter_lines(story):
        idx = int(k) if k.isdigit() else -1
        if idx < 0 or idx >= len(segs):
            err.append('lines[%s]: 段索引越界（共 %d 段）' % (k, len(segs)))
            continue
        text = str(line.get('text') or '').strip()
        if not text:
            err.append('lines[%s]: text 为空' % k)
            continue
        # 4) 说话人
        cast = (segs[idx] or {}).get('cast') or []
        if not str(line.get('speaker') or '').strip() and len(cast) != 1:
            err.append('lines[%s]: 没写 speaker 且本镜头有 %d 个角色 → 必须指名谁在说' % (k, len(cast)))
        # 5) 时长匹配
        need = max(base_sec, int(len(text) * SEC_PER_CHAR) + 1)
        seg_sec = int((segs[idx] or {}).get('seconds') or base_sec)
        if seg_sec < need:
            warn.append('lines[%s]: 台词 %d 字约需 %ds，本段只有 %ds（story_film 会自动抬到 %ds）'
                        % (k, len(text), need, seg_sec, need))
    return err, warn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('剧本 JSON 预检')
    ap.add_argument('story')
    a = ap.parse_args(argv)
    data = json.loads(Path(a.story).read_text(encoding='utf-8-sig'))
    err, warn = lint(data)
    for e in err:
        print('LINT_ERROR: ' + e)
    for w in warn:
        print('LINT_WARN: ' + w)
    print('LINT_SUMMARY: errors=%d warnings=%d' % (len(err), len(warn)))
    return 1 if err else 0


if __name__ == '__main__':
    sys.exit(main())
