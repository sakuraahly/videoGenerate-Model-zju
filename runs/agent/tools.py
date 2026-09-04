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
        if not script_name.endswith('.py'):
            return '错误：只允许执行 .py 脚本'

        script_path = _resolve(os.path.join(PROJECT_ROOT, 'runs', script_name))
        if not _is_under(script_path, _ALLOWED_SCRIPT_DIRS):
            return f'错误：脚本 {script_name} 不在白名单目录 runs/ 下'
        if not os.path.isfile(script_path):
            return f'错误：脚本不存在 {script_name}'

        cmd = [sys.executable, script_path]
        if extra_args:
            cmd.extend(extra_args.split())

        env = None
        if script_name == 'h3_submit.py' and '--dry-run' in (extra_args or ''):
            env = {**os.environ, 'H3_CONCISE': '1'}  # 精简 JSON 刷屏，防上下文膨胀

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SCRIPT_TIMEOUT,
                cwd=PROJECT_ROOT,
                env=env,
            )
            stdout = _truncate(result.stdout)
            stderr = _truncate(result.stderr)

            if result.returncode != 0:
                return (
                    f'脚本退出码 {result.returncode}\n'
                    f'stdout: {stdout}\nstderr: {stderr}'
                )
            return f'执行成功 (exit 0)\nstdout: {stdout}'

        except subprocess.TimeoutExpired as e:
            _out = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode('utf-8', errors='replace') if e.stdout else '')
            _err = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode('utf-8', errors='replace') if e.stderr else '')
            partial = _truncate(
                (_out + '\n' + _err).strip()
            )
            pid_line = next(
                (ln.strip() for ln in _out.splitlines()
                 if ln.startswith(('TASK_SUBMITTED:', 'prompt_id:'))),
                '',
            )
            note = f'任务已提交并在后台继续运行：{pid_line}。' if pid_line else ''
            if partial:
                return (
                    f'执行超时 ({_SCRIPT_TIMEOUT}s)：{note}'
                    f'（进程被限时中断，但 ComfyUI 上的任务不受影响）\n'
                    f'partial output:\n{partial}\n'
                    f'下一步：再次无参运行 h3_submit.py 续传查询，直到返回 '
                    f'REMOTE_VIDEO_PATH / LOCAL_OUTPUT。'
                )
            return f'错误：脚本执行超时 ({_SCRIPT_TIMEOUT}s)'
        except Exception as e:
            return f'错误：{e}'


@register_tool('modify_workflow')
class ModifyWorkflow(BaseTool):
    description = (
        '修改工作流 JSON 文件中指定节点的字段。'
        '仅允许修改 workflows/remote_workflows/ 下的文件。'
        '用于调整参考图路径（LoadImage 的 widgets_values）、分辨率等结构性参数。'
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
                    '{"<node_id>": {"widgets_values": ["new_image.png"]}} '
                    '或 {"<node_id>": {"mode": 4}}，'
                    'node_id 为节点的整数 ID（字符串形式）。'
                    '常见操作：修改 LoadImage 节点的 widgets_values[0] 更换参考图。'
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

            nodes = data.get('nodes', [])
            node_index = {n.get('id'): n for n in nodes if isinstance(n, dict)}

            modified_nodes = []
            for node_id_str, node_updates in changes.items():
                try:
                    node_id = int(node_id_str)
                except (ValueError, TypeError):
                    return f'错误：节点 ID 必须是整数，收到 {node_id_str}'

                if node_id not in node_index:
                    return f'错误：节点 ID {node_id} 在工作流中不存在'

                node = node_index[node_id]
                node.update(node_updates)
                modified_nodes.append(str(node_id))

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
        '通过 h3_submit 引擎向 ComfyUI 提交视频/图片生成任务。'
        '阶段：t2v(文生视频)、i2v(图生视频)、r2v(参考图生视频)、flf2v(首尾帧)。'
        '默认“提交即返回”（wait_until_done=false）：任务在后台运行，工具立即返回 '
        'TASK_SUBMITTED: prompt_id，不会长时间阻塞；之后用 run_script 运行 '
        'runs/h3_submit.py（不带参数）即可查询/续传直到完成并取回产物。'
        '设置 wait_until_done=true 才会在本调用内等待完成（视频生成通常数分钟）。'
        'dry_run=true 只校验参数不消耗 GPU。spark-local 下完成后视频会自动保存到'
        '项目 outputs/ 目录（输出含 LOCAL_OUTPUT 行）。'
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
            'wait_until_done': {
                'type': 'boolean',
                'description': (
                    '默认 false=提交即返回 prompt_id（任务后台运行，稍后用 run_script '
                    '无参跑 h3_submit.py 查询/取回）；true=在本调用内阻塞等待至完成'
                ),
            },
            'force_new': {
                'type': 'boolean',
                'description': 'true=忽略遗留断点强制开新任务',
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
            env = {**os.environ, 'H3_CONCISE': '1'}  # 精简输出：防长 JSON 撑爆对话
        elif not params.get('wait_until_done'):
            # 提交/等待分离：默认提交即返回，任务后台运行（不阻塞、不误报超时）
            cmd.append('--submit-only')
            env = None
        else:
            env = None
        if params.get('force_new'):
            cmd.append('--force-new')
        if params.get('prompt'):
            cmd.extend(['--prompt', params['prompt']])

        tool_timeout = 600 if params.get('wait_until_done') else 180

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=tool_timeout,
                cwd=PROJECT_ROOT,
                env=env,
            )
            stdout = _truncate(result.stdout)
            stderr = _truncate(result.stderr)

            if result.returncode != 0:
                return (
                    f'提交失败 (exit {result.returncode})\n'
                    f'stdout: {stdout}\nstderr: {stderr}'
                )
            return f'提交成功\n{stdout}'

        except subprocess.TimeoutExpired as e:
            _out = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode('utf-8', errors='replace') if e.stdout else '')
            _err = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode('utf-8', errors='replace') if e.stderr else '')
            partial = _truncate(
                (_out + '\n' + _err).strip()
            )
            pid_line = next(
                (ln.strip() for ln in _out.splitlines()
                 if ln.startswith(('TASK_SUBMITTED:', 'prompt_id:'))),
                '',
            )
            note = f'任务已提交并在后台继续运行：{pid_line}。' if pid_line else ''
            if partial:
                return (
                    f'调用等待超时：{note}（生成通常需数分钟）\n'
                    f'partial output:\n{partial}\n'
                    f'下一步：用 run_script 运行 h3_submit.py（不带参数）无参重跑续传，'
                    f'直到返回 REMOTE_VIDEO_PATH / LOCAL_OUTPUT。'
                )
            return f'错误：提交超时（{tool_timeout}s）'
        except Exception as e:
            return f'错误：{e}'


_ALLOWED_DOC_DIRS = [
    os.path.join(PROJECT_ROOT, 'docs', 'agent-reading'),
]


@register_tool('list_references')
class ListReferences(BaseTool):
    description = (
        '列出可作参考的素材：ComfyUI 已保存的图片（历次生成产物）、input 图库、'
        '以及 Open WebUI 上传收件箱里的文件。返回素材 id 列表。'
        '选择参考图时：先调本工具看有哪些可用素材，再用 run_script 运行 '
        'runs/h3/refimage.py promote --name <id|文件名>（放进 ComfyUI input）或 '
        'use --name <id|文件名> --stage r2v（把该图设为某阶段模板的参考图）。'
        '参考图视频生成用 call_comfyui(stage="r2v" / "i2v" / "flf2v")。'
    )
    parameters = {
        'type': 'object',
        'properties': {},
        'required': [],
    }

    def call(self, params: Union[str, dict], **kwargs) -> str:
        script = os.path.join(PROJECT_ROOT, 'runs', 'h3', 'refimage.py')
        if not os.path.isfile(script):
            return f'错误：refimage.py 不存在于 {script}'
        try:
            result = subprocess.run(
                [sys.executable, script, 'list'],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=PROJECT_ROOT,
            )
            out = _truncate((result.stdout or '') + (result.stderr or ''))
            if result.returncode != 0:
                return f'列出素材失败 (exit {result.returncode})\n{out}'
            return f'可用参考素材：\n{out}'
        except subprocess.TimeoutExpired:
            return '错误：列出素材超时'
        except Exception as e:
            return f'错误：{e}'


@register_tool('read_doc')
class ReadDoc(BaseTool):
    description = (
        '读取 docs/agent-reading/ 目录下的参考文档（Markdown 格式）。'
        '可用文档包括：00-project-overview.md（项目概览）、01-tools-reference.md（工具参考）、'
        '02-prompt-rules.md（提示词规则）、03-models-and-environment.md（模型环境）、'
        '04-agent-workflow.md（任务执行协议：提交/续传/取件）。'
        '用于在任务前了解项目能力和限制。'
    )
    parameters = {
        'type': 'object',
        'properties': {
            'filename': {
                'type': 'string',
                'description': '文档文件名，如 00-project-overview.md',
            },
        },
        'required': ['filename'],
    }

    def call(self, params: Union[str, dict], **kwargs) -> str:
        params = self._verify_json_format_args(params)
        filename = params['filename']

        if '..' in filename or filename.startswith('/'):
            return '错误：文档路径不合法（禁止 .. 或绝对路径）'
        if not filename.endswith(('.md', '.txt')):
            return '错误：只允许读取 .md 或 .txt 文件'

        doc_path = _resolve(os.path.join(
            PROJECT_ROOT, 'docs', 'agent-reading', filename,
        ))
        if not _is_under(doc_path, _ALLOWED_DOC_DIRS):
            return f'错误：文档 {filename} 不在允许目录内'
        if not os.path.isfile(doc_path):
            return f'错误：文档不存在 {filename}'

        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return _truncate(content)
        except Exception as e:
            return f'错误：{e}'


# read_doc 的工具描述随 docs/agent-reading 目录自动更新（新增文档无需改代码）
_doc_dir = os.path.join(PROJECT_ROOT, 'docs', 'agent-reading')
if os.path.isdir(_doc_dir):
    _doc_files = sorted(f for f in os.listdir(_doc_dir)
                        if f.lower().endswith(('.md', '.txt')))
    if _doc_files:
        try:
            ReadDoc.description = (
                ReadDoc.description.split('可用文档包括：')[0]
                + '可用文档包括：' + '、'.join(_doc_files)
                + '。用于在任务前了解项目能力与执行协议。'
            )
        except Exception:  # noqa: BLE001
            pass


# ---- 工具调用审计日志（透明包装：不改变 schema/行为；调用统一落 logs/run_*.log） ----
_TOOL_NAMES = {RunScript: 'run_script', ModifyWorkflow: 'modify_workflow',
               CallComfyUI: 'call_comfyui', ReadDoc: 'read_doc',
               ListReferences: 'list_references'}


def _log_tool(name, event, **fields):
    try:
        runs_dir = os.path.join(PROJECT_ROOT, 'runs')
        if runs_dir not in sys.path:
            sys.path.insert(0, runs_dir)
        from h3 import logutil
        logutil.ensure_run_log(PROJECT_ROOT, 'agent-tools')
        text = ' '.join('{0}={1}'.format(k, v) for k, v in fields.items())
        logutil.log_event(name, event + (' ' + text if text else ''))
    except Exception:
        pass


def _wrap_call(cls):
    orig = cls.call
    name = _TOOL_NAMES[cls]

    def wrapped(self, params, **kwargs):
        p = params if isinstance(params, str) else json.dumps(params, ensure_ascii=False)
        _log_tool(name, 'call', params=_truncate(p, 300))
        try:
            out = orig(self, params, **kwargs)
        except Exception as e:  # noqa: BLE001
            _log_tool(name, 'error', err=_truncate(str(e), 300))
            raise
        _log_tool(name, 'ok', out_len=len(out))
        return out

    wrapped.__name__ = orig.__name__
    wrapped.__doc__ = orig.__doc__
    wrapped.__module__ = orig.__module__
    wrapped.__annotations__ = dict(getattr(orig, '__annotations__', {}))
    cls.call = wrapped


for _cls in (RunScript, ModifyWorkflow, CallComfyUI, ReadDoc, ListReferences):
    _wrap_call(_cls)