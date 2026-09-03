# Qwen3.8-27B 部署与优化指南

> DGX Spark (GB10) · Grace Blackwell · AArch64 · 统一内存 ~122GB · CUDA 13.0 · SM 12.1
>
> 最后更新: 2026-09-03

---

## 目录

1. [概述](#1-概述)
2. [模型下载](#2-模型下载)
3. [推理引擎安装](#3-推理引擎安装)
4. [启动服务](#4-启动服务)
5. [API 使用](#5-api-使用)
6. [Web UI 配置](#6-web-ui-配置)
7. [服务管理](#7-服务管理)
8. [优化项说明](#8-优化项说明)
9. [故障排查](#9-故障排查)

---

## 1. 概述

本项目在 NVIDIA DGX Spark (GB10) 上部署 Qwen3.8-27B 大语言模型，采用三项核心优化：

| 优化项 | 说明 | 效果 |
|--------|------|------|
| NVFP4 量化 | RadixArk 混合精度量化 (MLP=NVFP4, Attn=FP8) | 模型 51GB → 21GB |
| SGLang 引擎 | 替代 vLLM，针对 GB10 优化 | 推理速度 ~40% 提升 |
| FlashInfer | 高效 attention 内核 (SM 12.1 适配) | 注意力计算加速 |

### 目录结构

```
~/Qwen3.8-27B/
├── models/
│   ├── NVFP4/                    # 量化模型 (21GB, 推荐)
│   └── Qwen--Qwen3.8-27B/       # 原始 bf16 模型 (~51GB)
├── sglang-venv/                  # SGLang 0.5.18 虚拟环境
├── vllm-venv/                    # vLLM 虚拟环境 (备用)
├── start_sglang.sh               # SGLang 启动脚本
├── start_vllm.sh                 # vLLM 启动脚本
├── smart_start_vllm.sh           # vLLM 智能启动 (自动避让 ComfyUI)
├── manage_services.sh            # 服务管理脚本
├── chat_terminal.py              # 终端对话脚本
├── install_flashinfer.sh         # FlashInfer 安装脚本
├── sglang.log                    # SGLang 运行日志
└── DEPLOYMENT.md                 # 本文档
```

---

## 2. 模型下载

### 2.1 原始 bf16 模型

来源: [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) (HuggingFace)

```bash
# 方式一: ModelScope (国内推荐)
pip install modelscope
modelscope download --model Qwen/Qwen3.8-27B --local_dir ~/Qwen3.8-27B/models/Qwen--Qwen3.8-27B

# 方式二: huggingface-cli
pip install huggingface_hub[hf_xet]
huggingface-cli download Qwen/Qwen3.8-27B --local-dir ~/Qwen3.8-27B/models/Qwen--Qwen3.8-27B
```

模型大小: ~51GB, 4 个 safetensors 分片

### 2.2 NVFP4 量化模型 (推荐)

来源: [RadixArk/Qwen3.8-27B-NVFP4](https://huggingface.co/RadixArk/Qwen3.8-27B-NVFP4)

```bash
# ModelScope 下载 (国内推荐, ~37 分钟 @7MB/s)
pip install modelscope
python3 -c "
from modelscope import snapshot_download
snapshot_download('RadixArk/Qwen3.8-27B-NVFP4',
                  local_dir='$HOME/Qwen3.8-27B/models/NVFP4')
"
```

模型大小: ~21GB, 3 个 safetensors 分片, ModelOpt 格式

量化精度分布:
- MLP 层: NVFP4 (4-bit)
- Attention 层: FP8 (8-bit)
- Vision / MTP 层: BF16 (原始精度)

---

## 3. 推理引擎安装

### 3.1 SGLang (推荐)

SGLang 0.5.18 在 GB10 上比 vLLM 快约 40%，内置 FlashInfer attention backend。

```bash
# 创建虚拟环境
python3 -m venv ~/Qwen3.8-27B/sglang-venv

# 安装 (国内使用阿里云镜像)
~/Qwen3.8-27B/sglang-venv/bin/pip install sglang==0.5.18 \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com
```

安装包含的关键组件:
- `sglang` 0.5.18 — 推理引擎
- `flashinfer_python` 0.6.17 — FlashInfer attention 内核
- `flash-attn-4` 4.0.0b19 — FlashAttention-4
- `humming-kernels` 0.1.10 — NVIDIA 优化内核
- `tilelang` 0.1.11 — GPU kernel 编译

### 3.2 vLLM (备用)

```bash
python3 -m venv ~/Qwen3.8-27B/vllm-venv
~/Qwen3.8-27B/vllm-venv/bin/pip install vllm \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com
```

---

## 4. 启动服务

### 4.1 SGLang (推荐)

```bash
# 方式一: 使用启动脚本 (自动检测 NVFP4/bf16)
cd ~/Qwen3.8-27B
bash start_sglang.sh              # 默认 NVFP4 模式
bash start_sglang.sh --bf16       # 使用 bf16 模型

# 方式二: 自定义参数
SGLANG_PORT=8001 SGLANG_MEM=0.88 bash start_sglang.sh

# 方式三: tmux 后台运行 (推荐)
tmux new-session -d -s sglang "bash ~/Qwen3.8-27B/start_sglang.sh 2>&1 | tee ~/Qwen3.8-27B/sglang.log"
```

启动参数说明:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `SGLANG_HOST` | 127.0.0.1 | 监听地址 |
| `SGLANG_PORT` | 8000 | 服务端口 |
| `SGLANG_MEM` | 0.95 | 静态内存占比 |
| `SGLANG_CTX_LEN` | 32768 | 最大上下文长度 |
| `SGLANG_CHUNK_SIZE` | 8192 | Chunked prefill 大小 |

NVFP4 模式额外启用:
- `--speculative-algorithm NEXTN` — MTP 推测解码
- `--speculative-num-steps 3` — 3 步推测
- `--speculative-eagle-topk 1` — TopK=1
- `--speculative-num-draft-tokens 4` — 4 个 draft tokens

### 4.2 vLLM (备用)

```bash
# 智能启动 (自动避让 ComfyUI)
bash ~/Qwen3.8-27B/smart_start_vllm.sh

# 或直接启动
bash ~/Qwen3.8-27B/start_vllm.sh
```

### 4.3 等待就绪

启动后需等待模型加载 (NVFP4 约 14 分钟)，日志出现以下信息表示就绪:

```
The server is fired up and ready to roll!
```

验证:
```bash
curl http://127.0.0.1:8000/health
```

---

## 5. API 使用

SGLang 完全兼容 OpenAI API 格式。

### 5.1 Chat Completions

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.8-27B",
    "messages": [{"role": "user", "content": "你好，介绍一下自己"}],
    "temperature": 0.7,
    "max_tokens": 512
  }'
```

### 5.2 模型信息

```bash
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/model_info
```

### 5.3 从本地 Windows 访问

通过 SSH 隧道转发:

```powershell
# 本地 PowerShell
ssh -L 8000:127.0.0.1:8000 spark

# 然后浏览器打开
# http://localhost:8000/docs   (Swagger API 文档)
```

### 5.4 Python 调用

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="sk-dummy")

response = client.chat.completions.create(
    model="Qwen3.8-27B",
    messages=[{"role": "user", "content": "你好"}],
    temperature=0.7,
    max_tokens=512,
)
print(response.choices[0].message.content)
```

### 5.5 终端对话

```bash
python3 ~/Qwen3.8-27B/chat_terminal.py
```

---

## 6. Web UI 配置

### 6.1 Open WebUI (推荐)

Open WebUI 提供类 ChatGPT 的网页对话界面。

```bash
# 方式一: pip 安装 (国内推荐)
python3 -m venv ~/open-webui-venv
~/open-webui-venv/bin/pip install open-webui \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

# 启动
OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1 \
OPENAI_API_KEY=sk-dummy \
~/open-webui-venv/bin/open-webui serve --host 0.0.0.0 --port 3000

# 方式二: Docker
docker run -d \
  --name open-webui \
  --network host \
  -e OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1 \
  -e OPENAI_API_KEY=sk-dummy \
  -v /home/Developer/open-webui/data:/app/backend/data \
  --restart always \
  ghcr.io/open-webui/open-webui:latest
```

访问:
- Spark 本机: http://localhost:3000
- 本地 Windows: 先 `ssh -L 3000:127.0.0.1:3000 spark`，再打开 http://localhost:3000

首次访问需注册管理员账号。在设置中添加 API 连接:
- API Base URL: `http://127.0.0.1:8000/v1`
- API Key: 任意值 (如 `sk-dummy`)

### 6.2 ChatGPT-Next-Web (轻量替代)

```bash
# Docker 部署
docker run -d \
  --name chatgpt-web \
  --network host \
  -e OPENAI_API_KEY=sk-dummy \
  -e BASE_URL=http://127.0.0.1:8000 \
  -e CODE=your-access-password \
  yidadaa/chatgpt-next-web:latest
```

---

## 7. 服务管理

使用 `manage_services.sh` 统一管理所有服务:

```bash
bash ~/Qwen3.8-27B/manage_services.sh status        # 查看所有服务状态
bash ~/Qwen3.8-27B/manage_services.sh start-sglang   # 启动 SGLang
bash ~/Qwen3.8-27B/manage_services.sh stop-sglang    # 停止 SGLang
bash ~/Qwen3.8-27B/manage_services.sh start-vllm     # 启动 vLLM
bash ~/Qwen3.8-27B/manage_services.sh stop-vllm      # 停止 vLLM
bash ~/Qwen3.8-27B/manage_services.sh start-comfyui  # 启动 ComfyUI
bash ~/Qwen3.8-27B/manage_services.sh stop-comfyui   # 停止 ComfyUI
bash ~/Qwen3.8-27B/manage_services.sh stop-all       # 停止所有服务
bash ~/Qwen3.8-27B/manage_services.sh health         # 健康检查
bash ~/Qwen3.8-27B/manage_services.sh gpu            # GPU 内存分布
```

### tmux 会话管理

```bash
tmux attach -t sglang     # 查看 SGLang 日志 (Ctrl+B D 退出)
tmux attach -t comfyui    # 查看 ComfyUI 日志
```

---

## 8. 优化项说明

### 8.1 NVFP4 量化

由 NVIDIA ModelOpt 生成的混合精度量化:
- 大幅减小模型体积 (51GB → 21GB)
- 利用 GB10 的 NVFP4 硬件加速
- 保持接近原始精度的输出质量
- 自动启用 NEXTN 推测解码 (MTP draft model)

### 8.2 SGLang vs vLLM

| 特性 | SGLang 0.5.18 | vLLM |
|------|---------------|------|
| GB10 性能 | 快 ~40% | 基准 |
| Attention Backend | FlashInfer | FlashInfer / FlashAttn |
| 推测解码 | NEXTN (内置 MTP) | 需额外配置 |
| CUDA Graph | 自动捕获 | 支持 |
| Radix Cache | 内置 | 无 |
| 内存管理 | Unified RadixCache | PagedAttention |

### 8.3 FlashInfer

SGLang 内置 `flashinfer_python` 0.6.17，已适配 SM 12.1 (Blackwell)。

首次启动时会自动:
1. JIT 编译 CUDA kernel (缓存到 `~/.cache/sglang/`)
2. 运行 autotune 选择最优 kernel 配置

后续启动直接使用缓存，无需重新编译。

---

## 9. 故障排查

### 模型加载失败

```bash
# 检查日志
tail -50 ~/Qwen3.8-27B/sglang.log

# 常见原因:
# - 内存不足: 降低 SGLANG_MEM (如 0.88)
# - 模型文件损坏: 重新下载
# - CUDA 版本不匹配: 确认 CUDA_HOME 指向正确路径
```

### 端口被占用

```bash
# 查看占用
lsof -i :8000
# 或换端口
SGLANG_PORT=8001 bash start_sglang.sh
```

### ComfyUI 冲突

`smart_start_vllm.sh` 会自动检测 ComfyUI 并调整 GPU 内存分配。使用 SGLang 时如遇到内存不足:

```bash
# 降低 SGLang 内存占比
SGLANG_MEM=0.80 bash start_sglang.sh
```

### FlashInfer JIT 编译慢

首次启动需编译 kernel，约 5-10 分钟。后续启动使用缓存。如缓存损坏:

```bash
rm -rf ~/.cache/sglang/flashinfer/
# 重启 SGLang 会重新编译
```

### SSH 隧道断开

```bash
# 本地 Windows 重新建立隧道
ssh -L 8000:127.0.0.1:8000 -N spark
```

---

## 快速参考

```bash
# 一键启动 (推荐)
tmux new-session -d -s sglang "bash ~/Qwen3.8-27B/start_sglang.sh 2>&1 | tee ~/Qwen3.8-27B/sglang.log"

# 等待 ~14 分钟后检查
ssh spark "tail -5 ~/Qwen3.8-27B/sglang.log"

# 测试 API
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.8-27B","messages":[{"role":"user","content":"你好"}]}'
```
