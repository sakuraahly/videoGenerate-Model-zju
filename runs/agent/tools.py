"""
受限调度器 — 3 个受控工具（适配 scheduler-agent-design.md）

工具：
  run_script       运行 runs/ 下白名单脚本
  modify_workflow  修改 workflows/remote_workflows/ 或 config/templates/ 下的工作流 JSON
  call_comfyui     经 h3_submit.py 引擎提交生成任务（不裸 POST）

安全：
  - realpath 前缀校验，禁止目录穿越
  - 输出截断 ≤5000 字符
  - 脚本执行超时 120s
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional, Union

from qwen_agent.tools import BaseTool
from qwen_agent.tools.base import register_tool

PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)

_ALLOWED_SCRIPT_DIRS = [
    os.path.join(PROJECT_ROOT, 'runs'),
]

_ALLOWED_WORKFLOW_DIRS = [
    os.path.join(PROJECT_ROOT, 'workflows', 'remote_workflows'),
    os.path.join(PROJECT_ROOT, 'config', 'templates'),
]

_MAX_OUTPUT = 5000
_SCRIPT_TIMEOUT = 120


def _resolve(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _is_under(path: str, allowed: list) -> bool:
    rp = _resolve(path)
    return any(rp.startswith(_resolve(d) + os.sep) or rp == _resolve(d)
               for d in allowed)


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f'\n... [truncated {len(text) - limit} chars]'


@register_tool('run_script')
class RunScript(BaseTool):
    description = (
        '运行项目 runs/ 目录下的白名单 Python 脚本。'
        '可用脚本：h3_submit.py（视频生成）、h3_text2img_flux.py（文生图）、'
        'h3/idea2prompts.py（提示词生成）等。脚本通过命令行参数接收输入。'
    )
    parameters = {
        'type': 'object',
        'properties': {
            'script_name': {
                'type': 'string',
                'description': '脚本相对路径，如 h3_submit.py 或 h3/idea2prompts.py',
            },
            'args': {
                'type': 'string',
                'description': '传给脚本的命令行参数，如 --stage t2v --seconds 10',
            },
        },
        'required': ['script_name'],
    }

    def call(self, params: Union[str, dict], **kwargs) -> str:
        params = self._verify_json_format_args(params)
        script_name = params['script_name']
        extra_args = params.get('args', '')

        if '..' in script_name or script_name.startswith('/'):
            return '错误：脚本路径不合法（禁止 .. 或绝对路径）'

        script_path = _resolve(os.path.join(PROJECT_ROOT, 'runs', script_name))
        if not _is_under(script_path, _ALLOWED_SCRIPT_DIRS):
            return f'错误：脚本 {script_name} 不在白名单目录 runs/ 下'
        if not os.path.isfile(script_path):
            return f'错误：脚本不存在 {script_name}'
        if not script_path.endswith('.py'):
            return '错误：只允许执行 .py 脚本'

        cmd = [sys.executable, script_path]
        if extra_args:
            cmd.extend(extra_args.split())

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SCRIPT_TIMEOUT,
                cwd=PROJECT_ROOT,
            )
            stdout = _truncate(result.stdout)
            stderr = _truncate(result.stderr)

            if result.returncode != 0:
                return (
                    f'脚本退出码 {result.returncode}\n'
                    f'stdout: {stdout}\nstderr: {stderr}'
                )
            return f'执行成功 (exit 0)\nstdout: {stdout}'

        except subprocess.TimeoutExpired:
            return f'错误：脚本执行超时 ({_SCRIPT_TIMEOUT}s)'
        except Exception as e:
            return f'错误：{e}'


@register_tool('modify_workflow')
class ModifyWorkflow(BaseTool):
    description = (
        '修改工作流 JSON 文件中指定节点的输入字段。'
        '仅允许修改 workflows/remote_workflows/ 和 config/templates/ 下的文件。'
        '用于调整参考图路径、分辨率等结构性参数。'
    )
    parameters = {
        'type': 'object',
        'properties': {
            'workflow_path': {
                'type': 'string',
                'description': '工作流相对路径，如 remote_workflows/video_minimax_h3_r2v.json',
            },
            'changes': {
                'type': 'string',
                'description': (
                    'JSON 格式修改内容，形如 '
                    '{"<node_id>": {"inputs": {"<field>": "<value>"}}}'
                ),
            },
        },
        'required': ['workflow_path', 'changes'],
    }

    def call(self, params: Union[str, dict], **kwargs) -> str:
        params = self._verify_json_format_args(params)
        wf_path = params['workflow_path']
        changes_str = params['changes']

        try:
            changes = json.loads(changes_str)
        except json.JSONDecodeError:
            return '错误：changes 不是合法 JSON'

        if '..' in wf_path or wf_path.startswith('/'):
            return '错误：路径不合法（禁止 .. 或绝对路径）'

        full_path = _resolve(os.path.join(PROJECT_ROOT, 'workflows', wf_path))
        if not _is_under(full_path, _ALLOWED_WORKFLOW_DIRS):
            return f'错误：{wf_path} 不在白名单目录内'
        if not full_path.endswith('.json'):
            return '错误：只允许修改 .json 文件'
        if not os.path.isfile(full_path):
            return f'错误：文件不存在 {wf_path}'

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            modified_nodes = []
            for node_id, node_changes in changes.items():
                if node_id in data:
                    node = data[node_id]
                    if isinstance(node, dict):
                        if 'inputs' not in node:
                            node['inputs'] = {}
                        node['inputs'].update(node_changes)
                        modified_nodes.append(node_id)
                else:
                    return f'错误：节点 {node_id} 在工作流中不存在'

            with open(full_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return f'已修改节点: {", ".join(modified_nodes)}，文件: {wf_path}'

        except json.JSONDecodeError:
            return f'错误：{wf_path} 不是合法 JSON'
        except Exception as e:
            return f'错误：{e}'


@register_tool('call_comfyui')
class CallComfyUI(BaseTool):
    description = (
        '通过 h3_submit 引擎提交视频/图片生成任务到 ComfyUI。'
        '支持阶段：t2v(文生视频)、i2v(图生视频)、r2v(参考图生视频)、flf2v(首尾帧)。'
        '可用 dry_run 验证参数而不消耗 GPU。'
    )
    parameters = {
        'type': 'object',
        'properties': {
            'stage': {
                'type': 'string',
                'enum': ['t2v', 'i2v', 'r2v', 'flf2v'],
                'description': '生成阶段类型',
            },
            'resolution': {
                'type': 'string',
                'enum': ['360p', '480p', '540p', '720p', '768p'],
                'description': '分辨率（可选）',
            },
            'seconds': {
                'type': 'integer',
                'description': '视频时长 5-15 秒（可选）',
            },
            'seed': {
                'type': 'integer',
                'description': '随机种子（可选）',
            },
            'dry_run': {
                'type': 'boolean',
                'description': '仅验证参数不实际生成',
            },
            'prompt': {
                'type': 'string',
                'description': '覆盖默认提示词（可选，默认从槽位文件读取）',
            },
        },
        'required': ['stage'],
    }

    def call(self, params: Union[str, dict], **kwargs) -> str:
        params = self._verify_json_format_args(params)
        stage = params['stage']

        submit_script = os.path.join(PROJECT_ROOT, 'runs', 'h3_submit.py')
        if not os.path.isfile(submit_script):
            return f'错误：h3_submit.py 不存在于 {submit_script}'

        cmd = [sys.executable, submit_script, '--stage', stage]

        if params.get('resolution'):
            cmd.extend(['--resolution', params['resolution']])
        if params.get('seconds'):
            cmd.extend(['--seconds', str(params['seconds'])])
        if params.get('seed') is not None:
            cmd.extend(['--seed', str(params['seed'])])
        if params.get('dry_run'):
            cmd.append('--dry-run')
        if params.get('prompt'):
            cmd.extend(['--prompt', params['prompt']])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=PROJECT_ROOT,
            )
            stdout = _truncate(result.stdout)
            stderr = _truncate(result.stderr)

            if result.returncode != 0:
                return (
                    f'提交失败 (exit {result.returncode})\n'
                    f'stdout: {stdout}\nstderr: {stderr}'
                )
            return f'提交成功\n{stdout}'

        except subprocess.TimeoutExpired:
            return '错误：提交超时 (600s)'
        except Exception as e:
            return f'错误：{e}'
