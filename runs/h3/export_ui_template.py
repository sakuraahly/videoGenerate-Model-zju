#!/usr/bin/env python3
"""export_ui_template — 把 API 工作流导出成**可被引擎读回**的 UI 模板（widget 值按节点定义顺序）。

为什么需要专门工具：`workflow.py::workflow_to_ui()` 生成的 UI 只保证连线正确，
widget 值沿用我们构建 API 时的输入顺序；而引擎的 UI→API 转换器（uiapi.py）
**严格按 object_info 的声明顺序消费 widget 值**，顺序不一致就会报
「有 N 个 widget 值无法按定义分配」并回退。
本工具按同一套规则**反过来生成**：
  · 按 required→optional 的声明顺序输出每个 widget 的值（值取自 API 输入，缺的用默认值）；
  · `control_after_generate` 紧随其数值 widget（补一个 fixed）；
  · 已连线（link）的输入不再输出 widget 值；
  · LoadImage 只输出 image 一个值。

用法（需能连到 ComfyUI 的 /object_info；在 spark 上跑最省事）：
  python3 runs/h3/export_ui_template.py --builtin-t2v --out workflows/remote_workflows/video_h3_t2v_builtin.json
  python3 runs/h3/export_ui_template.py --api workflows/h3_xxx/workflow_api.json --out /tmp/x.json [--object-info oi.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runs'))

_WIDGET_PRIMITIVES = {'INT', 'FLOAT', 'STRING', 'BOOLEAN', 'COMBO'}


def _spec_kind(spec):
    """与 uiapi._spec_kind 保持一致：value / dynamic / connectable / skip。"""
    if not isinstance(spec, (list, tuple)) or not spec:
        return 'skip'
    s0 = spec[0]
    if isinstance(s0, str):
        if s0 == 'COMFY_DYNAMICCOMBO_V3':
            return 'dynamic'
        if s0 in _WIDGET_PRIMITIVES:
            return 'value'
        return 'connectable'
    if isinstance(s0, list):
        return 'value'
    return 'skip'


def _cfg(spec):
    return spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}


def _default_value(name, spec):
    cfg = _cfg(spec)
    if 'default' in cfg:
        return cfg['default']
    s0 = spec[0]
    if isinstance(s0, list) and s0:
        first = s0[0]
        return first.get('value') if isinstance(first, dict) else first
    if s0 == 'INT':
        return 0
    if s0 == 'FLOAT':
        return 0.0
    if s0 == 'BOOLEAN':
        return False
    return ''


def _widget_values_for(node_type, api_inputs, object_info):
    """按 object_info 声明顺序产出该节点的 widgets_values（None = 定义未知，保持原样）。"""
    info = (object_info or {}).get(node_type)
    if not info:
        return None
    linked = {k for k, v in (api_inputs or {}).items()
              if isinstance(v, list) and len(v) == 2 and not isinstance(v[0], (int, float))}
    out = []
    for section in ('required', 'optional'):
        for name, spec in ((info.get('input') or {}).get(section) or {}).items():
            kind = _spec_kind(spec)
            if kind not in ('value', 'dynamic'):
                continue
            if name in linked:
                continue
            cfg = _cfg(spec)
            out.append(api_inputs.get(name, _default_value(name, spec)))
            if cfg.get('control_after_generate'):
                out.append('fixed')
    return out


def export(api_workflow: dict, object_info: dict) -> dict:
    from h3 import workflow as h3workflow
    ui = h3workflow.workflow_to_ui(api_workflow)
    api_by_id = api_workflow
    # workflow_to_ui 会把字符串 id 映射为 int；这里按 class_type+顺序对齐（节点少，够用）
    api_nodes = [v for _, v in sorted(api_by_id.items(), key=lambda kv: str(kv[0]))]
    for node in (ui.get('nodes') or []):
        t = node.get('type')
        api_in = None
        for cand in api_nodes:
            if cand.get('class_type') == t:
            # 同名多节点（如两个 VAELoader）：按出现顺序取，取过就删
                api_in = cand.get('inputs') or {}
                api_nodes.remove(cand)
                break
        vals = _widget_values_for(t, api_in or {}, object_info)
        if vals is not None:
            node['widgets_values'] = vals
    return ui


def main(argv=None) -> int:
    ap = argparse.ArgumentParser('导出可被引擎读回的 UI 模板')
    ap.add_argument('--api', default='', help='输入 API 工作流 JSON')
    ap.add_argument('--builtin-t2v', action='store_true', help='用内置 h3_t2v 生成器构建 API 工作流')
    ap.add_argument('--out', required=True)
    ap.add_argument('--object-info', default='', help='/object_info 的 JSON 文件（不给则从 ComfyUI 拉）')
    a = ap.parse_args(argv)
    oi = {}
    if a.object_info and Path(a.object_info).is_file():
        oi = json.loads(Path(a.object_info).read_text(encoding='utf-8-sig'))
    else:
        import urllib.request
        try:
            oi = json.loads(urllib.request.urlopen('http://127.0.0.1:8188/object_info', timeout=60).read())
        except Exception as e:
            print('EXPORT_UI_ERROR: 取不到 object_info（%s）' % str(e)[:120])
            return 1
    if a.builtin_t2v:
        from h3 import workflow as h3workflow
        pos = (ROOT / 'prompts' / 'positive_prompts.txt').read_text(encoding='utf-8').strip()
        neg = (ROOT / 'prompts' / 'negative_prompts.txt').read_text(encoding='utf-8').strip()
        api = h3workflow.build_workflow(pos, 864, 480, 124, 12345,
                                        negative_prompt=neg, steps=20, fps=24.0)
    else:
        api = json.loads(Path(a.api).read_text(encoding='utf-8-sig'))
    ui = export(api, oi)
    ui['_comment'] = ('由 runs/h3/export_ui_template.py 生成：widget 值按节点定义顺序排列，引擎可读回。'
                      '引擎提交时会覆写提示词与参数，这里的值只是基线。')
    Path(a.out).write_text(json.dumps(ui, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('EXPORT_UI_OK: %s（节点 %d，未知定义节点 %d）'
          % (a.out, len(ui.get('nodes') or []),
             sum(1 for n in (ui.get('nodes') or []) if n.get('type') not in oi)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
