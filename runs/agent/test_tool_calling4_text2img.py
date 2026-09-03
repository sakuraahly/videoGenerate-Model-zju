#!/usr/bin/env python3
"""Test 4: 文生图 — 让 Qwen agent 调用 h3_text2img.py 生成图片

测试提示词：用文生图生成一张 goodboy 图片
预期：agent 调用 run_script("h3_text2img.py", args='--prompt "..." --output goodboy')
"""
import os
import sys

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
请用中文回答。生成图片用 h3_text2img.py，生成视频用 call_comfyui。
"""


def main():
    bot = Assistant(
        llm=LLM_CFG,
        system_message=SYSTEM,
        function_list=['run_script', 'modify_workflow', 'call_comfyui'],
    )

    # 用户原始需求
    prompt = '调用本地 ComfyUI 生成一张图片，命名为 goodboy'

    print(f'>>> 用户输入: {prompt}')
    print('---')

    messages = [{'role': 'user', 'content': prompt}]

    response = []
    for chunk in bot.run(messages=messages):
        response = chunk

    if response:
        for msg in response:
            role = msg.get('role', '?')
            content = msg.get('content', '')
            if role == 'assistant':
                print(f'[assistant] {content[:1000]}')
            elif role == 'tool':
                print(f'[tool] {content[:1000]}')
        print('--- DONE ---')
    else:
        print('NO RESPONSE')


if __name__ == '__main__':
    main()
