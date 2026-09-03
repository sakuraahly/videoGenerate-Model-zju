"""
受限调度器 — 主入口（适配 scheduler-agent-design.md）

Qwen3.8-27B 作为受限调度器：理解意图 → 选工具 + 生成参数 → 工具层执行。
模型不直接执行命令，所有动作经白名单工具。

Usage:
    python3 runs/agent/scheduler.py              # Gradio Web UI (port 7860)
    python3 runs/agent/scheduler.py --cli         # 终端交互
    python3 runs/agent/scheduler.py --port 7861   # 自定义端口
"""
from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)
os.environ['VIDEOGEN_PROJECT_ROOT'] = _PROJECT_ROOT

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from runs.agent.tools import RunScript, ModifyWorkflow, CallComfyUI  # noqa: E402, F401

LLM_CFG = {
    'model': 'Qwen3.8-27B',
    'model_server': 'http://127.0.0.1:8000/v1',
    'api_key': 'sk-dummy',
    'generate_cfg': {
        'temperature': 0.2,
        'top_p': 0.8,
        'max_tokens': 4096,
        'fncall_prompt_type': 'nous',
    },
}

SYSTEM_MESSAGE = """\
你是 Qwen3.8-27B 受限调度器，运行在 DGX Spark 本地服务器上。

你的职责是理解用户的创意意图，然后通过受控工具完成视频/图片生成任务。

你可以使用以下 3 个工具：
1. run_script — 运行项目 runs/ 目录下的白名单脚本：
   - h3_submit.py（视频生成，支持 t2v/i2v/r2v/flf2v 阶段）
   - h3_text2img.py（文生图，生成单张图片）
   - h3/idea2prompts.py（提示词生成）
2. modify_workflow — 修改 workflows/remote_workflows/ 下的工作流 JSON（调整参考图、分辨率等结构性参数）
3. call_comfyui — 通过引擎提交视频生成任务（支持 t2v/i2v/r2v/flf2v 阶段）

重要限制：
- 你不能直接执行 shell 命令、管理服务、修改系统文件
- 所有文件操作限制在白名单目录内
- 生成类任务建议先用 dry_run=true 验证参数
- 请用中文回答

典型工作流：
- 文生视频：call_comfyui(stage="t2v", seconds=10)
- 文生图片：run_script("h3_text2img.py", args='--prompt "描述" --output goodboy')
- 先生参考图再做参考视频：run_script("h3_text2img.py", ...) → call_comfyui(stage="r2v")
- 验证参数：call_comfyui(stage="t2v", dry_run=true)
"""

TOOL_NAMES = ['run_script', 'modify_workflow', 'call_comfyui']


def _detect_project_root() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.dirname(os.path.dirname(script_dir))
    if os.path.isfile(os.path.join(candidate, 'config', 'pipeline.json')):
        return candidate
    return _PROJECT_ROOT


def run_gui(port: int = 7860, share: bool = False):
    from qwen_agent.agents import Assistant
    from qwen_agent.gui import WebUI

    bot = Assistant(
        llm=LLM_CFG,
        system_message=SYSTEM_MESSAGE,
        function_list=TOOL_NAMES,
    )

    print(f'Qwen-Agent 调度器 Web UI: http://127.0.0.1:{port}')
    print(f'项目根目录: {_detect_project_root()}')
    ui = WebUI(bot)
    ui.run(server_port=port, share=share)


def run_cli():
    from qwen_agent.agents import Assistant

    bot = Assistant(
        llm=LLM_CFG,
        system_message=SYSTEM_MESSAGE,
        function_list=TOOL_NAMES,
    )

    messages = []
    print('Qwen-Agent 受限调度器 CLI')
    print(f'项目根目录: {_detect_project_root()}')
    print('输入 quit 退出')
    print('=' * 50)

    while True:
        try:
            user_input = input('\n你: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n再见!')
            break

        if not user_input:
            continue
        if user_input.lower() == 'quit':
            print('再见!')
            break

        messages.append({'role': 'user', 'content': user_input})

        response = []
        for chunk in bot.run(messages=messages):
            response = chunk

        if response:
            last = response[-1]
            content = last.get('content', '')
            print(f'\n调度器: {content}')
            messages = messages + response


def main():
    parser = argparse.ArgumentParser(description='Qwen-Agent 受限调度器')
    parser.add_argument('--cli', action='store_true', help='终端交互模式')
    parser.add_argument('--port', type=int, default=7860, help='Web UI 端口')
    parser.add_argument('--share', action='store_true', help='Gradio 公网分享')
    args = parser.parse_args()

    if args.cli:
        run_cli()
    else:
        run_gui(port=args.port, share=args.share)


if __name__ == '__main__':
    main()
