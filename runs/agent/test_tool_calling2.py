#!/usr/bin/env python3
"""Test 2: run_script tool + multi-step reasoning"""
import os, sys

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
请用中文回答。
"""

bot = Assistant(
    llm=LLM_CFG,
    system_message=SYSTEM,
    function_list=['run_script', 'modify_workflow', 'call_comfyui'],
)

# Test run_script with idea2prompts --dry-run
messages = [{'role': 'user', 'content': '用 idea2prompts 脚本 dry-run 模式，给 video_t2v 工作流生成提示词，创意是：赛博朋克风格的东京街头'}]

print('>>> 发送: idea2prompts dry-run for video_t2v')
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
