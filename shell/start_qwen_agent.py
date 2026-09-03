#!/usr/bin/env python3
"""
Qwen-Agent 受限调度器 — 启动入口

连接本地 SGLang 推理服务，提供 3 个受控工具：
  run_script / modify_workflow / call_comfyui

Usage:
    python3 ~/Qwen3.8-27B/start_qwen_agent.py              # Gradio Web UI
    python3 ~/Qwen3.8-27B/start_qwen_agent.py --cli         # 终端交互
    python3 ~/Qwen3.8-27B/start_qwen_agent.py --port 7861   # 自定义端口
"""
import os
import sys

PROJECT_ROOT = os.path.expanduser('~/videoGenerate-Model-zju')
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from runs.agent.scheduler import main  # noqa: E402

if __name__ == '__main__':
    main()
