# H3 Video Generation Toolbox

MiniMax H3（Hailuo-03）视频生成自动化工具集：本地 Windows 编排层 + 远程 Linux GPU 主机上的 ComfyUI 本地推理。输入一段场景描述，产出带原生立体声音轨的视频（`outputs/video_N.mp4`）。

## 功能

- **一条命令生成**：`run.bat` 立即用当前参数生成；`menu.bat` 提供交互菜单（立即 / 定时 HH:MM / 延迟 N 分钟 / 改参数 / 环境自检 / 工作流工具）
- **多种生成阶段**：文生视频（t2v）、图生视频（i2v）、多参考图生视频（r2v）、首尾帧生视频（flf2v），支持本地模板与已保存工作流提交
- **UI→API 自动转换**：ComfyUI UI 格式工作流在线扁平化为 API 格式（`runs/h3/uiapi.py`），无需手工改 JSON
- **断点续传**：网络中断自动恢复（`last_job.json`），绝不重复生成
- **SSH 隧道自愈**：自动重连包装器 + keepalive，应对 NAT 空闲断连
- **运行审计**：每次运行落盘 `workflows/h3_<时间戳>/`（API/UI 工作流 + job.json 运行记录）

## 快速开始

```bat
menu.bat        &:: 选 [5] 环境自检（本地工具 + ssh 连通 + 远程模型核对）
edit.bat        &:: 设置 resolution (360p–768p) 与 seconds
run.bat         &:: 立即生成，产物在 outputs\
```

提示词默认读 `prompts/positive_prompts.txt` 与 `prompts/negative_prompts.txt`。写提示词前请遵循 `skills/h3-prompt-engineering.md` 的规则（时长+镜头开场、物理动作描述、中文字符逐个枚举、音频分层、负面约束收尾）。

## 前置要求

- 远程主机（ssh 别名 `spark`）上部署 ComfyUI 并监听 `127.0.0.1:8188`
- MiniMax H3 四件套模型（清单与 sha256 见 `config/minimax_h3_models.json`，可自动从 ModelScope 补货）
- 本地 Windows：PowerShell、Python、OpenSSH
- （可选）复制 `config/pipeline.example.json` 为 `config/pipeline.json`，把远程路径替换为你自己的用户名目录；缺失时内置 t2v 阶段仍可用

## 目录结构

```
menu.bat / run.bat / edit.bat     入口脚本
shell/        PowerShell 编排层（菜单、生成、定时、自检、隧道）
runs/         Python CLI 与 h3 引擎（工作流构建、提交、断点、隧道）
config/       环境配置、模型清单、阶段注册表、模板（pipeline.json 不入库，示例见 pipeline.example.json）
prompts/      正/负面提示词
parameters/   video.txt 生成参数
workflows/    模板镜像（h3_* 运行审计目录运行期生成，不入库）
docs/         运维与架构文档
skills/       AI agent 技能卡（生成流程 + 提示词工程）
outputs/      生成产物（不入库）
```

## 文档

| 文档 | 内容 |
|---|---|
| `docs/user-guide.md` | 用户手册：入口、配置、常见流程、断点恢复 |
| `docs/robustness-and-modularity.md` | 架构分层、扩展方法、可靠性设计 |
| `docs/h3-workflow-architecture.md` | 14 节点 API 工作流、模型文件、帧数网格 |
| `docs/h3-troubleshooting.md` | 故障排查手册 |
| `docs/comfyui-startup-and-access.md` | ComfyUI 启动、SSH 隧道与 NAT keepalive |
| `docs/manual-use-6-workflows.md` | 6 个官方工作流模板的手动使用法 |
| `docs/h3-manual-operations.md` | 全手动 SSH 操作流程（备用） |
| `docs/long-term-maintenance.md` | 长期维护：清理、更新、巡检 |
| `skills/h3-video-generation.md` | AI agent 生成任务技能卡 |
| `skills/h3-prompt-engineering.md` | H3 提示词工程规则 |

## 说明

本仓库只包含编排与自动化代码，**不含**模型权重与视频产物。生成在远程 ComfyUI 上本地推理完成，不依赖任何云端 API。
