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

from runs.agent.tools import (RunScript, ModifyWorkflow, CallComfyUI, ReadDoc,  # noqa: E402, F401
                              ListReferences)

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
你是 Qwen3.8-27B 受限调度器，运行在 DGX Spark (GB10) 本地服务器上。
你的职责是理解用户的创意意图，通过受控工具完成视频/图片生成任务。

═══ 核心知识（已内嵌，无需工具调用） ═══

【项目架构】Windows 工作站 + 远程 DGX Spark。Spark 上运行 ComfyUI + H3 视频模型 + SGLang(Qwen3.8-27B)。
【你的能力】
  - call_comfyui(stage) — 提交视频生成任务。stage: t2v(文生视频)/i2v(图生视频)/r2v(参考图)/flf2v(首末帧)
  - run_script(script, args) — 运行白名单 .py 脚本:
    · h3_submit.py — 视频生成（call_comfyui 的底层实现）
    · h3_text2img.py — 文生图: --prompt "描述" --output 名称 [--resolution 720p]
    · h3/idea2prompts.py — 提示词生成: --idea "创意" [--workflow 类型]
  - modify_workflow(workflow_path, changes) — 修改工作流 JSON 节点
  - read_doc(filename) — 读取 docs/agent-reading/ 下的参考文档
  - list_references() — 列出可作参考的素材（ComfyUI 已保存图/input 图库/上传收件箱），
    配合 run_script 运行 h3/refimage.py 使用：refimage.py list / promote --name <id>
    / use --name <id> --stage r2v（把选中图设为模板参考图）

【硬性限制 — 必须遵守】
  ✗ 不能执行 shell 命令、管理服务（ComfyUI/SGLang/tmux 等）
  ✗ 不能读写项目白名单目录以外的文件
  ✗ 不能执行非 .py 脚本
  → 用户要求上述操作时，拒绝并告知需人工操作

【模型信息】Spark 上只有 H3 视频模型（无 SD/SDXL）:
  diffusion_model 21GB + text_encoder 16GB + video VAE 5.2GB
  文生图 = 生成 5 帧极短视频 → 取中间帧保存为图片

【分辨率】360p(608×352) / 480p / 540p / 720p(1280×736,推荐) / 768p(1344×768)
【时长】0.1-600秒，推荐 5-15秒。帧数满足 17k+5 网格。

【提示词规则】英文、具体描述（主体+环境+光影+风格+镜头运动）、避免模糊词汇。

═══ 任务前参考文档（可选，按需调用 read_doc） ═══
如需更详细信息，可用 read_doc 读取:
  - 00-project-overview.md — 完整能力清单和路径表
  - 01-tools-reference.md — 工具参数详细说明
  - 02-prompt-rules.md — 提示词工程完整规则和示例
  - 03-models-and-environment.md — 模型清单和服务端口

═══ 典型工作流 ═══
- 文生视频: call_comfyui(stage="t2v", prompt="...", seconds=10)
- 文生图片: run_script("h3_text2img.py", args='--prompt "a good boy" --output goodboy')
- 参考图视频: call_comfyui(stage="r2v", prompt="...")
- 验证参数: call_comfyui(stage="t2v", dry_run=true)

请用中文回答。
"""

TOOL_NAMES = ['run_script', 'modify_workflow', 'call_comfyui', 'read_doc',
               'list_references']


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
