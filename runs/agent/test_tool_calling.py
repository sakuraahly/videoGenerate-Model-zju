#!/usr/bin/env python3
"""Quick test: does qwen-agent actually invoke tools end-to-end?"""
import os, sys, json

PROJECT_ROOT = os.environ.get('VIDEOGEN_PROJECT_ROOT', os.path.expanduser('~/videoGenerate-Model-zju'))
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
请用中文回答。测试时先用 dry_run=true。
"""

bot = Assistant(
    llm=LLM_CFG,
    system_message=SYSTEM,
    function_list=['run_script', 'modify_workflow', 'call_comfyui'],
)

messages = [{'role': 'user', 'content': '帮我用 dry_run 模式验证一下 t2v 文生视频的参数，5秒 360p'}]

print('>>> 发送: 帮我用 dry_run 模式验证一下 t2v 文生视频的参数，5秒 360p')
print('---')

response = []
for chunk in bot.run(messages=messages):
    response = chunk

if response:
    for msg in response:
        role = msg.get('role', '?')
        content = msg.get('content', '')
        if role == 'assistant':
            print(f'[assistant] {content[:500]}')
        elif role == 'tool':
            print(f'[tool] {content[:500]}')
        elif role == 'user':
            pass
        else:
            print(f'[{role}] {content[:200]}')
    print('--- DONE ---')
else:
    print('NO RESPONSE')
