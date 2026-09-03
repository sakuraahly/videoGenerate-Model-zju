#!/usr/bin/env python3
"""Test 3: modify_workflow tool — does the agent find and update nodes correctly?

Uses api_minimax_h3_r2v.json (small file, LoadImage node id=2).
Makes a backup, runs the test, restores the original.
"""
import os
import sys
import shutil
import json

PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)
sys.path.insert(0, PROJECT_ROOT)
os.environ['VIDEOGEN_PROJECT_ROOT'] = PROJECT_ROOT

from runs.agent.tools import RunScript, ModifyWorkflow, CallComfyUI  # noqa: F401
from qwen_agent.agents import Assistant

LLM_CFG = {
    'model': 'Qwen3.8-27B',
    'model_server': 'http://127.0.0.1:8000/v1',
    'api_key': 'sk-dummy',
    'generate_cfg': {
        'temperature': 0.2,
        'top_p': 0.8,
        'max_tokens': 2000,
        'fncall_prompt_type': 'nous',
    },
}

SYSTEM = """\
你是受限调度器。可用工具：run_script / modify_workflow / call_comfyui。
请用中文回答。
"""

WORKFLOW_FILE = 'remote_workflows/api_minimax_h3_r2v.json'
WORKFLOW_FULL = os.path.join(PROJECT_ROOT, 'workflows', WORKFLOW_FILE)
BACKUP = WORKFLOW_FULL + '.bak'


def main():
    shutil.copy2(WORKFLOW_FULL, BACKUP)
    print(f'[setup] 已备份 {WORKFLOW_FILE} → .bak')

    try:
        bot = Assistant(
            llm=LLM_CFG,
            system_message=SYSTEM,
            function_list=['run_script', 'modify_workflow', 'call_comfyui'],
        )

        prompt = (
            '请修改工作流 remote_workflows/api_minimax_h3_r2v.json，'
            '把 LoadImage 节点（id=2）的 widgets_values 里的图片名改成 drama_asset_villain.png'
        )
        messages = [{'role': 'user', 'content': prompt}]

        print(f'>>> 发送: {prompt}')
        print('---')

        response = []
        for chunk in bot.run(messages=messages):
            response = chunk

        if response:
            for msg in response:
                role = msg.get('role', '?')
                content = msg.get('content', '')
                if role == 'assistant':
                    print(f'[assistant] {content[:800]}')
                elif role == 'tool':
                    print(f'[tool] {content[:800]}')
            print('--- DONE ---')
        else:
            print('NO RESPONSE')

        with open(WORKFLOW_FULL, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for node in data.get('nodes', []):
            if node.get('id') == 2:
                wv = node.get('widgets_values', [])
                print(f'\n[verify] LoadImage(id=2) widgets_values[0] = {wv[0] if wv else "EMPTY"}')
                if wv and wv[0] == 'drama_asset_villain.png':
                    print('[PASS] 修改成功')
                else:
                    print('[FAIL] 修改未生效')
                break

    finally:
        shutil.copy2(BACKUP, WORKFLOW_FULL)
        os.remove(BACKUP)
        print(f'\n[cleanup] 已恢复原始文件')


if __name__ == '__main__':
    main()
