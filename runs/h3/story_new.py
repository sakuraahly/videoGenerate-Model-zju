#!/usr/bin/env python3
"""story_new — 把 agent 写好的剧本 JSON 落盘 + 预检（agent 唯一可用的"写文件"通道）。

背景（2026-09-10）：agent 的工具集里**没有写文件的工具**（只有 run_script 跑白名单脚本），
所以"让 agent 写剧本"必须先有一个落盘入口，否则它会一直卡在"找不到工具"。
本脚本就是那个入口：接收内联 JSON（推荐 base64，避免引号/空格被 shell 拆坏）→
写到 config/story_<name>.json → 立刻跑 story_lint 预检并返回结论。

用法（agent 侧）：
  run_script(h3/story_new.py, --name umbrella --b64 <base64(JSON)>)
  run_script(h3/story_new.py, --name umbrella --json '{"title":...}')     # 短 JSON 可直接内联
  python3 runs/h3/story_new.py --name umbrella --json-file /tmp/s.json    # 本地/调试
选项：--print 回显落盘内容；--no-lint 跳过预检。
退出码：0=已落盘且预检无错误；1=参数/写盘/lint 有错；2=JSON 解析失败（原样回显错误）
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runs.h3 import story_lint as _lint  # noqa: E402


def _load_payload(a) -> str:
    if a.json_file:
        return Path(a.json_file).read_text(encoding='utf-8-sig')
    if a.b64:
        try:
            return base64.b64decode(a.b64.encode()).decode('utf-8')
        except Exception as e:  # noqa: BLE001
            raise ValueError('base64 解码失败: %s' % e)
    if a.json:
        return a.json
    raise ValueError('必须给 --json / --b64 / --json-file 之一')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('剧本落盘 + 预检')
    ap.add_argument('--name', required=True, help='片名标识（落盘为 config/story_<name>.json）')
    ap.add_argument('--json', default='', help='内联 JSON（短剧本可用）')
    ap.add_argument('--b64', default='', help='base64(JSON)（推荐：不会被 shell 引号拆坏）')
    ap.add_argument('--json-file', default='', help='从文件读 JSON')
    ap.add_argument('--print', action='store_true', help='回显落盘内容')
    ap.add_argument('--no-lint', action='store_true', help='跳过预检')
    a = ap.parse_args(argv)
    try:
        raw = _load_payload(a)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('剧本 JSON 顶层必须是对象')
    except Exception as e:  # noqa: BLE001
        print('STORY_NEW_ERROR: JSON 解析失败: %s' % str(e)[:200])
        print('提示：用 --b64（base64 编码后的 JSON）最稳，例如 base64 编码后再传。')
        return 2
    name = ''.join(ch for ch in str(a.name) if ch.isalnum() or ch in '_-')
    if not name:
        print('STORY_NEW_ERROR: --name 不合法（只允许字母数字下划线连字符）')
        return 1
    dst = ROOT / 'config' / ('story_%s.json' % name)
    try:
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError as e:
        print('STORY_NEW_ERROR: 写盘失败: %s' % e)
        return 1
    print('STORY_NEW_OK: %s（%d 段 / %d 句台词）'
          % (dst.relative_to(ROOT), len(data.get('segments') or []), len(data.get('lines') or {})))
    if a.print:
        print(dst.read_text(encoding='utf-8'))
    if a.no_lint:
        return 0
    err, warn = _lint.lint(data)
    for e in err:
        print('LINT_ERROR: ' + e)
    for w in warn:
        print('LINT_WARN: ' + w)
    print('LINT_SUMMARY: errors=%d warnings=%d' % (len(err), len(warn)))
    if err:
        print('下一步: 修掉 LINT_ERROR 后重新调用本脚本（不必重新生成整份剧本）。')
        return 1
    print('下一步: run_script(h3/story_film.py, --story %s --stitch --out outputs/%s.mp4)'
          % (dst.relative_to(ROOT), name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
