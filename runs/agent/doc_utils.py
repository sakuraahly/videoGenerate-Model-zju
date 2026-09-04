"""doc_utils — 文档扫描工具函数（从 tools.py 提取，避免循环依赖）。

供 tools.py（ReadDoc 动态描述）和 doc_state.py（文档变化检测）共同使用。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)


def scan_agent_reading_docs() -> list:
    """扫描 docs/agent-reading/ 目录，返回 [(filename, mtime, size), ...]。"""
    doc_dir = os.path.join(PROJECT_ROOT, 'docs', 'agent-reading')
    if not os.path.isdir(doc_dir):
        return []
    results = []
    for f in sorted(os.listdir(doc_dir)):
        if f.lower().endswith(('.md', '.txt')):
            fp = os.path.join(doc_dir, f)
            try:
                st = os.stat(fp)
                results.append((f, st.st_mtime, st.st_size))
            except OSError:
                continue
    return results
