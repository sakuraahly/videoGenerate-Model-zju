# Qwen3.8-27B 本地模型快速启动指南

> DGX Spark (GB10) 上的 Qwen3.8-27B 一键部署手册

## 环境概览

| 项目 | 值 |
|------|-----|
| 硬件 | NVIDIA DGX Spark (Grace Blackwell GB10) |
| 架构 | AArch64 (ARM64), CUDA 13.0, SM 12.1 |
| 统一内存 | ~121.69 GiB (124500 MiB) |
| 模型 | Qwen3.8-27B (bf16, 52 GB) |
| 推理引擎 | vLLM 0.28.0 / SGLang 0.5.17 |
| 服务端口 | 8000 (vLLM/SGLang), 8188 (ComfyUI) |

## 快速启动（3 步）

### 1. 连接远程主机

```bash
ssh spark
```

### 2. 启动服务

```bash
# 方式 A（推荐）：SGLang + NVFP4 量化模型 — 最快，23 tok/s
bash ~/Qwen3.8-27B/manage_services.sh start-sglang

# 方式 B：vLLM 智能启动（自动检测 ComfyUI 并调整参数）
bash ~/Qwen3.8-27B/manage_services.sh start-vllm

# 方式 C：手动指定参数
VLLM_MAX_LEN=8192 VLLM_GPU_MEM=0.55 bash ~/Qwen3.8-27B/start_vllm.sh
```

### 3. 开始对话

```bash
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
| vLLM + FP8 | 14.8 tok/s | 29 GB | |
| vLLM + bf16 | 基准 | 52 GB | 原始精度 |

## 服务管理

```bash
# 统一管理器
bash ~/Qwen3.8-27B/manage_services.sh <命令>
```

| 命令 | 说明 |
|------|------|
| `status` | 查看所有服务状态 |
| `start-sglang` | 启动 SGLang（推荐） |
| `stop-sglang` | 停止 SGLang |
| `start-vllm` | 启动 vLLM |
| `stop-vllm` | 停止 vLLM |
| `start-comfyui` | 启动 ComfyUI |
| `stop-comfyui` | 停止 ComfyUI |
| `stop-all` | 停止所有服务 |
| `health` | 健康检查 |
| `gpu` | 查看 GPU 状态 |

## 内存配置速查

### 与 ComfyUI 共存

当 ComfyUI 运行时（占用 ~32 GB），模型参数自动调整为：

- `max-model-len`: 8192 tokens
- `gpu-memory-utilization`: 0.55
- 预计可用 KV 缓存: ~15 GB

### 独立运行

无其他 GPU 进程时：

- `max-model-len`: 32768 tokens
- `gpu-memory-utilization`: 0.88
- 预计可用 KV 缓存: ~55 GB

## 常见问题

### vLLM 启动失败？

```bash
# 检查日志
tail -50 ~/qwen-serve.log

# 检查 GPU 内存
nvidia-smi

# 停止其他 GPU 进程后重试
bash ~/Qwen3.8-27B/manage_services.sh stop-comfyui
```

### fp8 KV 缓存报错？

当前 FlashInfer 在 SM 12.1 (Blackwell) 上存在兼容性问题。默认使用 `auto`（FlashAttention v2），无需手动处理。

### 内存不足？

```bash
# 降低 max-model-len
VLLM_MAX_LEN=4096 VLLM_GPU_MEM=0.45 bash ~/Qwen3.8-27B/start_vllm.sh
```

## 文件位置

| 文件 | 远程路径 |
|------|----------|
| SGLang 启动脚本 | `~/Qwen3.8-27B/start_sglang.sh` |
| vLLM 启动脚本 | `~/Qwen3.8-27B/start_vllm.sh` |
| 智能启动脚本 | `~/Qwen3.8-27B/smart_start_vllm.sh` |
| 服务管理器 | `~/Qwen3.8-27B/manage_services.sh` |
| 终端对话 | `~/Qwen3.8-27B/chat_terminal.py` |
| FlashInfer 安装 | `~/Qwen3.8-27B/install_flashinfer.sh` |
| NVFP4 量化模型 | `~/Qwen3.8-27B/models/NVFP4/` |
| bf16 原始模型 | `~/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master/` |
| Python 环境 (vLLM) | `~/Qwen3.8-27B/vllm-venv/` |
| Python 环境 (SGLang) | `~/Qwen3.8-27B/sglang-venv/` |

---

详细手册请参阅 [full-manual.md](full-manual.md)
