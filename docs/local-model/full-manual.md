# Qwen3.8-27B 完整技术手册

> DGX Spark (GB10) 本地大模型部署全参考

## 目录

1. [硬件平台](#1-硬件平台)
2. [模型详情](#2-模型详情)
3. [推理引擎](#3-推理引擎)
4. [部署架构](#4-部署架构)
5. [脚本详解](#5-脚本详解)
6. [内存管理](#6-内存管理)
7. [性能优化](#7-性能优化)
8. [故障排查](#8-故障排查)
9. [进阶配置](#9-进阶配置)

---

## 1. 硬件平台

### DGX Spark 规格

| 参数 | 值 |
|------|-----|
| SoC | NVIDIA Grace Blackwell GB10 |
| CPU | NVIDIA Grace (ARM64/AArch64) |
| GPU | Blackwell架构, SM 12.1 |
| 统一内存 | 128 GB (可用 ~121.69 GiB / 124500 MiB) |
| CUDA | 13.0 |
| 内存类型 | LPDDR5X (CPU/GPU 共享) |

### 关键特性

- **统一内存架构**: CPU 和 GPU 共享同一物理内存池，无需 PCIe 传输
- **高带宽**: 内存带宽 ~273 GB/s
- **ARM64 架构**: 所有软件需 ARM64 兼容版本
- **SM 12.1**: Blackwell 计算能力，部分 CUDA kernel 尚需适配

---

## 2. 模型详情

### Qwen3.8-27B

| 参数 | 值 |
|------|-----|
| 架构 | `Qwen3_5ForConditionalGeneration` |
| 参数量 | 27B |
| 精度 | bfloat16 (bf16) |
| 磁盘大小 | ~52 GB |
| 层数 | 64 |
| 隐藏层维度 | 5120 |
| 注意力机制 | 混合线性注意力 (Gated DeltaNet) + 标准注意力 |
| 多模态 | 支持图像和视频输入 |
| 上下文长度 | 最大 65536 tokens (需显式配置) |

### 模型文件结构

```
~/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master/
├── config.json              # 模型配置
├── tokenizer.json           # 分词器
├── tokenizer_config.json
├── model-00001-of-00014.safetensors  # 模型权重 (14 分片)
├── model-00002-of-00014.safetensors
├── ...
├── model-00014-of-00014.safetensors
└── model.safetensors.index.json
```

### 量化模型选项（GB10 实测数据）

| 格式 | 大小 | 解码速度 | 引擎 | 说明 |
|------|------|----------|------|------|
| **NVFP4 (RadixArk)** | ~21 GB | **23 tok/s** | SGLang | 混合精度: MLP=NVFP4, Attn=FP8, Vision/MTP=BF16。**推荐** |
| GGUF Q4_K_M | ~17 GB | 21.4 tok/s | llama.cpp | 最低内存，PPL 损失可忽略 |
| GGUF Q6_K | ~23 GB | 20.2 tok/s | llama.cpp | 更高精度，配合 DSpark |
| NVFP4 + MTP k=3 | ~21 GB | 17.8 tok/s | vLLM | vLLM 上的 NVFP4 方案 |
| FP8 | ~29 GB | 14.8 tok/s | vLLM | 全精度基准 |
| bf16 (原始) | 52 GB | 基准 | vLLM | 无量化，最大内存占用 |

> 数据来源: GB10 实测报告，SGLang + NVFP4 + NEXTN 推测解码配置

### 已下载的量化模型

```
~/Qwen3.8-27B/models/
├── Qwen--Qwen3.8-27B/snapshots/master/   # bf16 原始模型 (52 GB)
└── NVFP4/                                 # RadixArk NVFP4 量化 (~21 GB)
```

---

## 3. 推理引擎

### vLLM 0.28.0

当前部署的主力引擎。

**已安装组件**:
- vLLM 0.28.0
- FlashAttention v2 (默认注意力后端)
- FlashInfer 0.6.16.post3 (采样后端, KV 缓存后端受限)
- PyTorch 2.13.0+cu130

**启动参数说明**:

```bash
python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \            # 模型路径
    --served-model-name "$NAME" \      # API 中的模型名称
    --host "127.0.0.1" \               # 监听地址
    --port 8000 \                       # 监听端口
    --tensor-parallel-size 1 \          # 张量并行数 (GB10 单 GPU, 固定为 1)
    --max-model-len 16384 \             # 最大上下文长度
    --gpu-memory-utilization 0.88 \     # GPU 内存利用率上限
    --kv-cache-dtype auto \             # KV 缓存数据类型 (auto/fp8)
    --trust-remote-code \               # 信任远程代码 (Qwen3.5 架构需要)
    --dtype bfloat16 \                  # 模型权重精度
    --limit-mm-per-prompt '{"image":4,"video":2}'  # 多模态限制
```

### SGLang 0.5.18（推荐）

GB10 上的首选引擎，配合 NVFP4 量化可达 **23 tok/s** 解码速度。

**优势**:
- 原生 FlashInfer 后端（默认使用，无需额外配置）
- RadixAttention KV 缓存管理，内存效率更高
- 针对 ARM64 + Blackwell 优化，有官方 aarch64 wheel
- 支持 NEXTN 推测解码，进一步提升吞吐量

**安装**:

```bash
# 创建独立虚拟环境（避免与 vLLM 冲突）
python3 -m venv ~/Qwen3.8-27B/sglang-venv

# 安装（有 aarch64 预编译 wheel）
~/Qwen3.8-27B/sglang-venv/bin/pip install "sglang[all]"

# 验证
~/Qwen3.8-27B/sglang-venv/bin/python -c "import sglang; print(sglang.__version__)"
```

**启动（NVFP4 模型）**:

```bash
~/Qwen3.8-27B/sglang-venv/bin/python -m sglang.launch_server \
    --model-path ~/Qwen3.8-27B/models/NVFP4 \
    --host 127.0.0.1 \
    --port 8000 \
    --tp 1 \
    --mem-fraction-static 0.95 \
    --context-length 32768 \
    --chunked-prefill-size 8192 \
    --disable-prefill-cuda-graph \
    --trust-remote-code
```

**或使用启动脚本**:

```bash
bash ~/Qwen3.8-27B/start_sglang.sh          # 默认使用 NVFP4
bash ~/Qwen3.8-27B/start_sglang.sh --bf16    # 回退到 bf16 模型
```

**GB10 优化参数说明**:

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `--mem-fraction-static` | 0.95 | KV 缓存内存比例 |
| `--chunked-prefill-size` | 8192 | 分块预填充大小，降低 TTFT |
| `--disable-prefill-cuda-graph` | (flag) | 禁用预填充 CUDA 图，TTFT 降低 ~47% |
| `--context-length` | 32768 | 最大上下文长度 |

### 引擎对比

| 特性 | vLLM | SGLang |
|------|------|--------|
| GB10 性能 | 基准 | ~40% 更快 |
| FlashInfer 集成 | 部分 (采样) | 完整 (默认后端) |
| KV 缓存管理 | PagedAttention | RadixAttention |
| 多模态支持 | 完善 | 完善 |
| ARM64 兼容性 | 已验证 | 需验证 |
| 社区活跃度 | 高 | 高 |

---

## 4. 部署架构

### 目录结构

```
~/Qwen3.8-27B/
├── vllm-venv/                    # vLLM 虚拟环境
├── sglang-venv/                  # SGLang 虚拟环境 (待创建)
├── models/
│   └── Qwen--Qwen3.8-27B/
│       └── snapshots/
│           └── master/           # 模型文件 (52 GB)
├── start_vllm.sh                 # vLLM 基础启动脚本
├── smart_start_vllm.sh           # 智能启动脚本
├── start_sglang.sh               # SGLang 启动脚本 (待创建)
├── manage_services.sh            # 统一服务管理器
├── install_flashinfer.sh         # FlashInfer 安装脚本
└── chat_terminal.py              # 终端对话客户端
```

### 服务拓扑

```
┌─────────────────────────────────────────────┐
│           DGX Spark (GB10)                  │
│                                             │
│  ┌──────────┐    ┌──────────┐              │
│  │ ComfyUI  │    │  vLLM /  │              │
│  │ :8188    │    │  SGLang  │              │
│  │ ~32 GB   │    │  :8000   │              │
│  └──────────┘    └──────────┘              │
│       ↑                 ↑                   │
│       │    共享 128 GB 统一内存    │          │
│       └─────────────────┘                   │
│                                             │
│  ~/.cache/vllm/  (torch.compile 缓存)      │
└─────────────────────────────────────────────┘
         ↑
         │ SSH
    ┌────┴────┐
    │ 本地机  │
    │  器     │
    └─────────┘
```

### API 接口

vLLM/SGLang 均提供 OpenAI 兼容 API：

```
GET  /health                    # 健康检查
GET  /v1/models                 # 列出模型
POST /v1/chat/completions       # 对话补全
POST /v1/completions            # 文本补全
POST /v1/embeddings             # 嵌入向量
```

---

## 5. 脚本详解

### start_vllm.sh — 基础启动脚本

最简单的启动方式，所有参数通过环境变量覆盖。

**环境变量**:

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VLLM_HOST` | 127.0.0.1 | 监听地址 |
| `VLLM_PORT` | 8000 | 监听端口 |
| `VLLM_MODEL_NAME` | Qwen3.8-27B | API 中的模型名 |
| `VLLM_TP` | 1 | 张量并行数 |
| `VLLM_MAX_LEN` | 16384 | 最大上下文长度 |
| `VLLM_GPU_MEM` | 0.88 | GPU 内存利用率 |
| `VLLM_KV_DTYPE` | auto | KV 缓存类型 |
| `VLLM_ALLOW_LONG_MAX_MODEL_LEN` | 1 | 允许超长上下文 |

### smart_start_vllm.sh — 智能启动脚本

自动检测运行环境并选择最优参数。

**检测逻辑**:

1. 检查 vLLM 是否已运行 (curl `:8000/health`)
2. 检测 ComfyUI 是否运行 (curl `:8188`)
3. 检测 FlashInfer 可用性 (Python import 测试)
4. 根据检测结果选择配置方案

**配置方案**:

| 方案 | 条件 | max_len | gpu_mem | 说明 |
|------|------|---------|---------|------|
| coexist | ComfyUI 运行中 | 8192 | 0.55 | 与 ComfyUI 共存 |
| standalone | 无其他 GPU 进程 | 32768 | 0.88 | 独立运行 |

**命令行参数**:

```bash
bash smart_start_vllm.sh [选项]

选项:
  --with-comfyui    强制使用共存模式
  --dry-run         仅显示参数，不实际启动
  --max-len=N       自定义最大上下文长度
```

### manage_services.sh — 服务管理器

统一管理 vLLM 和 ComfyUI 的生命周期。

**tmux 会话**:

| 会话名 | 服务 | 说明 |
|--------|------|------|
| `vllm` | vLLM/SGLang | 推理服务 |
| `comfyui` | ComfyUI | 图像生成 |

**ComfyUI 启动参数**:

```bash
cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py \
    --listen 127.0.0.1 \
    --port 8188 \
    --disable-auto-launch \
    --reserve-vram 12     # 预留 12 GB 给其他进程
```

### install_flashinfer.sh — FlashInfer 安装脚本

两阶段安装策略：

1. **预编译 wheel**: 尝试直接安装适配版本
2. **源码编译**: 若预编译失败，从源码构建

**关键环境变量**:

```bash
MAX_JOBS=2                    # 限制编译并行数，防止 OOM
FLASHINFER_CUDA_ARCHS="12.1"  # 指定 Blackwell 架构
```

---

## 6. 内存管理

### 统一内存分配

GB10 的 128 GB 统一内存在 CPU 和 GPU 之间动态分配，但 GPU 进程（如 vLLM）通过 `gpu-memory-utilization` 参数预留固定比例。

### 内存预算计算

```
总内存:                    124500 MiB (~121.69 GiB)
模型权重 (bf16):           ~52200 MiB (~51.0 GiB)
CUDA 上下文 + 开销:        ~5000 MiB
──────────────────────────────────────
独立模式可用 KV 缓存:      ~57300 MiB (gpu_mem=0.88)
共存模式可用 KV 缓存:      ~16500 MiB (gpu_mem=0.55)
```

### KV 缓存与上下文长度

KV 缓存大小直接影响可服务的上下文长度：

| 模式 | KV 缓存 (估算) | 可用 tokens |
|------|---------------|-------------|
| bf16, standalone | ~55 GB | ~32768 |
| bf16, coexist | ~15 GB | ~8192 |
| fp8, standalone | ~27 GB | ~65536 (理论) |
| fp8, coexist | ~8 GB | ~16384 (理论) |

> 注: fp8 KV 缓存当前因 SM 12.1 兼容性问题不可用

### 内存优化策略

1. **降低 max-model-len**: 最直接的方式，减少 KV 缓存预留
2. **使用 fp8 KV 缓存**: 节省 ~50% KV 内存 (待 SM 12.1 修复)
3. **NVFP4 量化模型**: 模型从 52 GB 降至 21 GB，释放 ~31 GB
4. **ComfyUI --reserve-vram**: 限制 ComfyUI 内存占用
5. **torch.compile 缓存**: `~/.cache/vllm/` 加速重复启动

---

## 7. 性能优化

### 已完成优化

- [x] 调整 `max-model-len` 从 65536 降至 16384（减少内存预留）
- [x] 调整 `gpu-memory-utilization` 从 0.90 降至 0.88
- [x] 添加 `--kv-cache-dtype` 参数支持
- [x] 智能启动脚本自动检测环境
- [x] ComfyUI `--reserve-vram 12` 限制内存占用
- [x] torch.compile 缓存 (`~/.cache/vllm/`)

### 计划中优化

- [ ] FlashInfer SM 12.1 修复 → 启用 fp8 KV 缓存
- [ ] RadixArk NVFP4 量化模型 → 模型体积减半
- [ ] SGLang 引擎 → ~40% 推理加速

### FlashInfer SM 12.1 问题

**现状**: FlashInfer 0.6.16.post3 已安装，但 `flashinfer_xqa_batch_decode_with_kv_cache` kernel 未针对 SM 12.1 编译。

**影响**: 无法使用 fp8 KV 缓存，回退到 FlashAttention v2。

**修复方案**:

```bash
# 方案 1: 从源码重编译 FlashInfer
MAX_JOBS=2 FLASHINFER_CUDA_ARCHS="12.1" \
    pip install flashinfer-python --no-binary :all:

# 方案 2: 等待官方发布 SM 12.1 预编译版本
# 关注: https://github.com/flashinfer-ai/flashinfer/issues
```

### SGLang 迁移路径

```bash
# 1. 创建独立环境
python3 -m venv ~/Qwen3.8-27B/sglang-venv
source ~/Qwen3.8-27B/sglang-venv/bin/activate

# 2. 安装 SGLang
pip install "sglang[all]"

# 3. 测试启动
python -m sglang.launch_server \
    --model-path ~/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master \
    --host 127.0.0.1 --port 8001 \
    --tp 1 --mem-fraction-static 0.88

# 4. 验证后切换主端口
```

---

## 8. 故障排查

### 启动类问题

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| `CUDA out of memory` | GPU 内存不足 | 降低 `VLLM_GPU_MEM` 或 `VLLM_MAX_LEN` |
| `Port 8000 already in use` | vLLM 已在运行 | `manage_services.sh stop-vllm` 后重试 |
| `Model loading timeout` | 模型加载超时 | 检查磁盘 I/O，等待完成 |
| `trust_remote_code` 错误 | 架构代码未信任 | 确保 `--trust-remote-code` 参数存在 |

### 性能类问题

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| 推理速度慢 | 内存带宽瓶颈 | 减少并发请求，降低 max_len |
| 首次响应慢 | torch.compile 编译 | 正常现象，后续请求会快 |
| KV 缓存频繁换出 | max_len 设置过高 | 降低 `VLLM_MAX_LEN` |

### ComfyUI 共存问题

| 症状 | 原因 | 解决方案 |
|------|------|----------|
| ComfyUI OOM | vLLM 占用过多 | 使用 `smart_start_vllm.sh` 自动调整 |
| vLLM OOM | ComfyUI 占用过多 | 增大 `--reserve-vram` 参数 |
| 端口冲突 | 服务未正确停止 | `tmux kill-session -t <name>` |

### 诊断命令

```bash
# GPU 状态
nvidia-smi

# GPU 进程详情
nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv

# tmux 会话
tmux ls

# vLLM 日志
tail -f ~/qwen-serve.log

# 内存使用
free -h

# 磁盘空间
df -h ~
```

---

## 9. 进阶配置

### 自定义模型路径

```bash
# 使用其他模型
MODEL_PATH=/path/to/other/model \
VLLM_MODEL_NAME=MyModel \
bash start_vllm.sh
```

### 网络暴露（远程访问）

```bash
# 警告: 直接暴露到网络存在安全风险
# 推荐: 使用 SSH 隧道
ssh -L 8000:127.0.0.1:8000 spark

# 或修改监听地址（仅限可信网络）
VLLM_HOST=0.0.0.0 bash start_vllm.sh
```

### 多实例运行

```bash
# 在不同端口运行第二个实例
VLLM_PORT=8001 VLLM_MAX_LEN=4096 VLLM_GPU_MEM=0.30 \
    bash start_vllm.sh
```

### 环境变量持久化

```bash
# 在 ~/.bashrc 中添加
export VLLM_MAX_LEN=16384
export VLLM_GPU_MEM=0.88
export VLLM_KV_DTYPE=auto
```

### 监控与日志

```bash
# 实时监控推理性能
watch -n 2 nvidia-smi

# vLLM 请求日志
tmux attach -t vllm

# ComfyUI 日志
tmux attach -t comfyui
```

---

## 附录: 版本信息

| 组件 | 版本 |
|------|------|
| vLLM | 0.28.0 |
| SGLang | 0.5.17 (计划) |
| FlashAttention | v2 |
| FlashInfer | 0.6.16.post3 |
| PyTorch | 2.13.0+cu130 |
| CUDA | 13.0 |
| Python | 3.x (venv 内) |
| Qwen3.8-27B | master snapshot |

---

*最后更新: 2026-09-03*
