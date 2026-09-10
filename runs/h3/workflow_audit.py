#!/usr/bin/env python3
"""workflow_audit — 只读审计：**现在引擎到底用哪份工作流**（2026-09-10）。

为什么不靠记忆：项目里有三处跟工作流有关的位置（pipeline.json 的注册表、引擎真正读取的镜像目录、
以及历史遗留的 config/templates），2026-09-10 就因为搞混它们而改错了文件。本工具把答案做成一条命令，
**只读、不改任何东西、不动提交路径**：

  1) 每个 stage 实际使用的模板（从 config/pipeline.json 解析）→ 是否存在 / sha1 / 节点数 / 格式；
  2) 镜像目录里**未注册**的模板（成品链等，只有 GUI 或 --template 显式指定才会用）；
  3) 过期目录 config/templates 与镜像同名文件的差异（提醒别在那里改）；
  4) 体检结论：注册的模板是否齐全（缺失 → 退出码 1）。

用法：
  python3 runs/h3/workflow_audit.py            # 人看的表
  python3 runs/h3/workflow_audit.py --json     # 机器可读
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPRECATED_DIR = 'config/templates'


def _sha1(p: Path) -> str:
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:8]
    except Exception:
        return ''


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception:
        return None


def _fmt(p: Path) -> str:
    d = _load_json(p)
    if isinstance(d, dict) and isinstance(d.get('nodes'), list):
        return 'ui'
    if isinstance(d, dict) and d and all(isinstance(v, dict) and 'class_type' in v for v in d.values()):
        return 'api'
    return '?'


def _nodes(p: Path):
    d = _load_json(p)
    if isinstance(d, dict) and isinstance(d.get('nodes'), list):
        return len(d['nodes'])
    if isinstance(d, dict):
        return len(d)
    return None


def audit(project_dir=None) -> dict:
    root = Path(project_dir or ROOT)
    try:
        sys.path.insert(0, str(root / 'runs'))
        from h3 import stage as h3stage
        cfg = h3stage.load_pipeline_config(root)
        tdir = h3stage.templates_dir(cfg, root)
    except Exception as e:
        return {'ok': False, 'error': '读不到 pipeline 配置: %s' % str(e)[:160], 'stages': [],
                'unregistered': [], 'deprecated_diff': [], 'missing': []}
    stages, missing = [], []
    for st in h3stage.list_stages(cfg):
        name = str(st.get('template') or '').strip()
        builtin = st.get('builtin')
        rec = {'stage': st.get('_id') or st.get('id'), 'template': name,
               'kind': str(st.get('template_kind') or ''), 'builtin': builtin or '',
               'dir': str(tdir.relative_to(root)) if str(tdir).startswith(str(root)) else str(tdir)}
        if builtin:
            rec.update({'path': '', 'exists': True, 'sha1': '', 'nodes': None, 'format': 'builtin'})
            stages.append(rec)
            continue
        p = (tdir / name) if name else Path()
        ok = bool(name) and p.is_file()
        rec.update({'path': (str(p.relative_to(root)) if name else ''), 'exists': ok,
                    'sha1': _sha1(p) if ok else '', 'nodes': _nodes(p) if ok else None,
                    'format': _fmt(p) if ok else '?'})
        if not ok:
            missing.append(rec)
        stages.append(rec)
    used = {r['template'] for r in stages if r['template']}
    unregistered = []
    if tdir.is_dir():
        for f in sorted(tdir.glob('*.json')):
            if f.name not in used:
                unregistered.append({'template': f.name, 'bytes': f.stat().st_size,
                                     'format': _fmt(f), 'nodes': _nodes(f), 'sha1': _sha1(f)})
    dep = []
    ddir = root / DEPRECATED_DIR
    if ddir.is_dir():
        for f in sorted(ddir.glob('*.json')):
            mirror = tdir / f.name
            dep.append({'template': f.name, 'in_mirror': mirror.is_file(),
                        'same': bool(mirror.is_file() and _sha1(mirror) == _sha1(f)),
                        'dep_sha1': _sha1(f), 'mirror_sha1': _sha1(mirror) if mirror.is_file() else ''})
    return {'ok': not missing, 'project': str(root), 'templates_dir': str(tdir),
            'stages': stages, 'unregistered': unregistered, 'deprecated_diff': dep,
            'deprecated_dir': DEPRECATED_DIR, 'missing': missing}


def render(rep: dict) -> str:
    if rep.get('error'):
        return 'WORKFLOW_AUDIT_ERROR: ' + rep['error']
    lines = ['镜像目录（引擎读取）: %s' % rep['templates_dir'], '',
             '%-10s %-6s %-8s %-42s %-9s %-6s %s' % ('stage', 'kind', 'format', '实际模板', 'sha1', 'nodes', '状态')]
    for r in rep['stages']:
        if r.get('builtin'):
            lines.append('%-10s %-6s %-8s %-42s %-9s %-6s %s'
                         % (r['stage'], 'builtin', 'builtin', '(内置生成器 %s)' % r['builtin'], '-', '-', 'OK'))
            continue
        lines.append('%-10s %-6s %-8s %-42s %-9s %-6s %s'
                     % (r['stage'], r['kind'] or '-', r['format'], r['template'], r['sha1'] or '-',
                        str(r['nodes'] if r['nodes'] is not None else '-'),
                        'OK' if r['exists'] else 'X 文件不存在'))
    lines.append('')
    if rep['unregistered']:
        lines.append('未注册模板（引擎不会自动用；GUI 手动或 --template 显式指定才用）:')
        for u in rep['unregistered']:
            lines.append('  - %-42s %6d B  %s%s' % (u['template'], u['bytes'], u['format'],
                                                    (' (%s 节点)' % u['nodes']) if u['nodes'] else ''))
    else:
        lines.append('未注册模板: 无')
    lines.append('')
    dep = rep.get('deprecated_diff') or []
    if dep:
        lines.append('过期目录 %s（引擎不读；同名文件与镜像对比）:' % rep['deprecated_dir'])
        for d in dep:
            mark = '一致' if d['same'] else ('与镜像不同 (!)' if d['in_mirror'] else '镜像里没有')
            lines.append('  - %-42s %s' % (d['template'], mark))
        lines.append('  -> 要改工作流请改镜像目录；本目录仅历史对照。')
    lines.append('')
    if rep['missing']:
        lines.append('WORKFLOW_AUDIT: FAIL —— %d 个 stage 指向的模板不存在: %s'
                     % (len(rep['missing']), ', '.join(m['template'] for m in rep['missing'])))
    else:
        lines.append('WORKFLOW_AUDIT: OK —— 注册的模板齐全（%d 个 stage）' % len(rep['stages']))
    return '\n'.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('工作流审计（只读）')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--project-dir', default='')
    a = ap.parse_args(argv)
    rep = audit(a.project_dir or None)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if a.json else render(rep))
    return 0 if rep.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
