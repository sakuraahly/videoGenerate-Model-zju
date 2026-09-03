# Agent 任务前必读 — 项目概览

> 每次接到任务前，先阅读本目录下的文件，了解项目能力和限制。

## 项目是什么

Windows 工作站 + 远程 DGX Spark (GB10) 的视频生成工具箱。
Spark 上运行 ComfyUI + H3 视频模型 + Qwen3.8-27B (SGLang) + Qwen-Agent + Open WebUI。

## 你能做什么

| 能力 | 工具/脚本 | 说明 |
|------|-----------|------|
| 文生视频 | call_comfyui(stage="t2v") | 文字描述 → 视频 |
| 图生视频 | call_comfyui(stage="i2v") | 首帧图 → 视频 |
| 参考图生视频 | call_comfyui(stage="r2v") | 1-2张参考图 → 连贯视频 |
| 首末帧生视频 | call_comfyui(stage="flf2v") | 首帧+末帧 → 视频 |
| 文生图 | run_script("h3_text2img.py") | H3模型生成5帧视频取中间帧 |
| 提示词生成 | run_script("h3/idea2prompts.py") | 创意 → 各槽位提示词JSON |
| 修改工作流 | modify_workflow(...) | 调整工作流JSON参数 |

## 你不能做什么（硬性限制）

- **不能**执行 shell 命令、管理服务、修改系统文件
- **不能**启动/停止 ComfyUI、SGLang、tmux 等
- **不能**读写项目 prompt 文件以外的路径
- **不能**执行非 .py 脚本
- 如果用户要求上述操作，**拒绝并告知需人工操作**

## 关键路径

| 用途 | 路径 |
|------|------|
| 视频生成脚本 | runs/h3_submit.py |
| 文生图脚本 | runs/h3_text2img.py |
| 提示词生成 | runs/h3/idea2prompts.py |
| 工作流模板 | workflows/remote_workflows/ |
| 参数配置 | parameters/video.txt |
| 管线配置 | config/pipeline.json |
| 输出目录 | outputs/ |

## 分辨率参考

| 预设 | 宽×高 | 说明 |
|------|--------|------|
| 360p | 608×352 | 最低质量 |
| 480p | 864×480 | |
| 540p | 960×544 | |
| 720p | 1280×736 | 推荐 |
| 768p | 1344×768 | 最高 |

时长：0.1-600秒，推荐5-15秒。帧数必须满足 17k+5 网格。
