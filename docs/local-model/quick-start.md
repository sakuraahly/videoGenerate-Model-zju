# Qwen3.8-27B 本地模型快速启动指南

> DGX Spark (GB10) 上的 Qwen3.8-27B 一键部署手册
> 最后更新: 2026-09-03

## 环境概览

| 项目 | 值 |
|------|-----|
| 硬件 | NVIDIA DGX Spark (Grace Blackwell GB10) |
| 架构 | AArch64 (ARM64), CUDA 13.0, SM 12.1 |
| 统一内存 | ~121.69 GiB (124500 MiB) |
| 模型 | Qwen3.8-27B (NVFP4, 21 GB) |
| 推理引擎 | SGLang 0.5.18（推荐）/ vLLM 0.28.0（备用） |
| 服务端口 | 8000 (SGLang), 8188 (ComfyUI), 7860 (Qwen-Agent), 3000 (Open WebUI) |

## 快速启动（3 步）

### 1. 连接远程主机

```bash
ssh spark
```

### 2. 启动所有服务（协调启动）

```bash
# 一键协调启动（自动处理 GPU 内存冲突）
bash ~/videoGenerate-Model-zju/shell/manage_services.sh start
```

协调启动顺序：停 ComfyUI → 加载 SGLang (2-3 min) → 启 ComfyUI → qwen-agent → Open WebUI

### 3. 开始使用

```bash
# 网页对话（Open WebUI）
# 浏览器打开 http://spark:3000

# Agent 调度器（Gradio Web UI）
# 浏览器打开 http://spark:7860

# 终端对话
python ~/Qwen3.8-27B/chat_terminal.py

# 或直接调用 API
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.8-27B","messages":[{"role":"user","content":"你好"}]}'
```

## 性能基准（GB10 实测）

| 配置 | 解码速度 | 模型大小 | 说明 |
|------|----------|----------|------|
| **SGLang + NVFP4** | **23 tok/s** | 21 GB | 推荐配置 |
| vLLM + NVFP4 | 17.8 tok/s | 21 GB | |
| vLLM + bf16 | 基准 | 52 GB | 原始精度 |

## 服务管理

```bash
# 统一管理脚本
bash ~/videoGenerate-Model-zju/shell/manage_services.sh <命令>
```

| 命令 | 说明 |
|------|------|
| `start` | 协调启动所有服务 |
| `stop` | 停止所有服务 |
| `restart` | 重启所有服务 |
| `status` | 查看所有服务状态 |
| `logs` | 查看最近日志 |
| `enable` | 启用开机自启 |
| `disable` | 禁用开机自启 |

## 开机自启

已配置 XDG autostart（`~/.config/autostart/spark-ai-services.desktop`），
开机自动协调启动所有服务。

## tmux 会话

| 会话名 | 服务 | 端口 |
|--------|------|------|
| `sglang` | SGLang 推理 | 8000 |
| `comfyui` | ComfyUI | 8188 |
| `qwen-agent` | Qwen-Agent 调度器 | 7860 |
| `webui` | Open WebUI | 3000 |

```bash
tmux attach -t sglang    # 查看日志（Ctrl+B D 退出）
```

## 内存配置

### 与 ComfyUI 共存（默认）

SGLang `--mem-fraction-static 0.55`，与 ComfyUI 共享 GPU 内存。

### 独立运行（独占 GPU）

编辑 `~/videoGenerate-Model-zju/shell/systemd/sglang-qwen.service`，
改 `--mem-fraction-static` 为 `0.95`。

## 常见问题

### SGLang 启动 OOM？

确保 ComfyUI 已停止后再启动 SGLang（协调启动脚本已处理）。

### Open WebUI 无法访问？

```bash
# 检查是否在运行
tmux has-session -t webui && echo "running" || echo "not running"

# 重启（注意 HF_HUB_OFFLINE=1）
tmux kill-session -t webui
tmux new-session -d -s webui 'source ~/open-webui-venv2/bin/activate && \
  HF_HUB_OFFLINE=1 OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1 \
  open-webui serve --host 0.0.0.0 --port 3000 2>&1 | tee /tmp/webui2.log'
```

## 文件位置

| 文件 | 远程路径 |
|------|----------|
| 协调启动脚本 | `~/videoGenerate-Model-zju/shell/start_all_services.sh` |
| 服务管理器 | `~/videoGenerate-Model-zju/shell/manage_services.sh` |
| SGLang 启动脚本 | `~/videoGenerate-Model-zju/shell/start_sglang_coexist.sh` |
| 终端对话 | `~/Qwen3.8-27B/chat_terminal.py` |
| Qwen-Agent 入口 | `~/videoGenerate-Model-zju/runs/agent/scheduler.py` |
| NVFP4 量化模型 | `~/Qwen3.8-27B/models/NVFP4/` |
| Python 环境 (SGLang) | `~/Qwen3.8-27B/sglang-venv/` |
| Python 环境 (Open WebUI) | `~/open-webui-venv2/` |
| Python 环境 (Qwen-Agent) | `~/qwen-agent-venv/` |

---

详细手册请参阅 [full-manual.md](full-manual.md) · 部署指南请参阅 [../qwen38-deployment.md](../qwen38-deployment.md)
