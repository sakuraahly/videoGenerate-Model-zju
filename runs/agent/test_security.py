#!/usr/bin/env python3
"""Security regression tests — verify tools reject malicious inputs.

No LLM needed: directly calls tool.call() with crafted params.
All tests should produce error messages (not execute anything dangerous).
"""
import os
import sys
import json
import types
import importlib.util

PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)
sys.path.insert(0, PROJECT_ROOT)
os.environ['VIDEOGEN_PROJECT_ROOT'] = PROJECT_ROOT

# Mock qwen_agent for local testing (only installed on spark)
if 'qwen_agent' not in sys.modules:
    _qa = types.ModuleType('qwen_agent')
    _qa_tools = types.ModuleType('qwen_agent.tools')

    class _BaseTool:
        def _verify_json_format_args(self, params):
            if isinstance(params, str):
                return json.loads(params)
            return params

    def _register_tool(name):
        def decorator(cls):
            return cls
        return decorator

    _qa_tools.BaseTool = _BaseTool
    _qa_tools.register_tool = _register_tool
    sys.modules['qwen_agent'] = _qa
    sys.modules['qwen_agent.tools'] = _qa_tools
    sys.modules['qwen_agent.tools.base'] = _qa_tools

# Load tools.py directly (no __init__.py in runs/agent/)
_tools_path = os.path.join(PROJECT_ROOT, 'runs', 'agent', 'tools.py')
_spec = importlib.util.spec_from_file_location('agent_tools', _tools_path)
_tools_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tools_mod)

RunScript = _tools_mod.RunScript
ModifyWorkflow = _tools_mod.ModifyWorkflow
CallComfyUI = _tools_mod.CallComfyUI

passed = 0
failed = 0


def check(label, result, should_contain='错误'):
    global passed, failed
    if should_contain in result:
        print(f'  [PASS] {label}: {result[:100]}')
        passed += 1
    else:
        print(f'  [FAIL] {label}: expected "{should_contain}" in result, got: {result[:200]}')
        failed += 1


def test_run_script_security():
    print('\n=== run_script 安全测试 ===')
    tool = RunScript()

    check(
        '目录穿越 ..',
        tool.call({'script_name': '../../etc/passwd', 'args': ''}),
    )
    check(
        '绝对路径 /etc/passwd',
        tool.call({'script_name': '/etc/passwd', 'args': ''}),
    )
    check(
        '非 .py 文件',
        tool.call({'script_name': 'h3_submit.sh', 'args': ''}),
        '只允许执行 .py',
    )
    check(
        '不存在的脚本',
        tool.call({'script_name': 'nonexistent.py', 'args': ''}),
        '不存在',
    )
    check(
        '嵌套穿越 runs/../../etc/passwd',
        tool.call({'script_name': 'h3/../../etc/passwd.py', 'args': ''}),
    )


def test_modify_workflow_security():
    print('\n=== modify_workflow 安全测试 ===')
    tool = ModifyWorkflow()

    check(
        '目录穿越 ..',
        tool.call({
            'workflow_path': '../../etc/config.json',
            'changes': '{}',
        }),
    )
    check(
        '绝对路径',
        tool.call({
            'workflow_path': '/etc/comfyui/workflow.json',
            'changes': '{}',
        }),
    )
    check(
        '非 .json 文件',
        tool.call({
            'workflow_path': 'remote_workflows/readme.txt',
            'changes': '{}',
        }),
        '只允许修改 .json',
    )
    check(
        '不存在的文件',
        tool.call({
            'workflow_path': 'remote_workflows/nonexistent.json',
            'changes': '{}',
        }),
        '不存在',
    )
    check(
        '非法 JSON changes',
        tool.call({
            'workflow_path': 'remote_workflows/api_minimax_h3_r2v.json',
            'changes': 'not-json',
        }),
        '不是合法 JSON',
    )
    check(
        '不存在的节点 ID',
        tool.call({
            'workflow_path': 'remote_workflows/api_minimax_h3_r2v.json',
            'changes': '{"99999": {"mode": 4}}',
        }),
        '不存在',
    )
    check(
        '非整数节点 ID',
        tool.call({
            'workflow_path': 'remote_workflows/api_minimax_h3_r2v.json',
            'changes': '{"abc": {"mode": 4}}',
        }),
        '必须是整数',
    )


def test_call_comfyui_security():
    print('\n=== call_comfyui 安全测试 ===')
    tool = CallComfyUI()

    result = tool.call({
        'stage': 't2v',
        'seconds': 5,
        'dry_run': True,
    })
    if '提交成功' in result or '执行成功' in result or 'exit' in result.lower():
        print(f'  [PASS] dry_run 正常执行: {result[:100]}')
        global passed
        passed += 1
    else:
        print(f'  [INFO] dry_run 结果: {result[:200]}')


def main():
    print('Qwen-Agent 工具安全回归测试')
    print(f'PROJECT_ROOT = {PROJECT_ROOT}')

    test_run_script_security()
    test_modify_workflow_security()
    test_call_comfyui_security()

    print(f'\n{"=" * 50}')
    print(f'结果: {passed} 通过, {failed} 失败')
    if failed:
        print('[WARN] 有安全测试失败！请检查 tools.py')
        sys.exit(1)
    else:
        print('[OK] 所有安全测试通过')


if __name__ == '__main__':
    main()
