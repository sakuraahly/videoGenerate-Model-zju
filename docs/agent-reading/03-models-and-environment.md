# Spark 模型与环境信息

## H3 视频模型（spark 上唯一可用的生成模型）

| 模型文件 | 大小 | 用途 |
|----------|------|------|
| diffusion_model (NVFP4) | 21 GB | 主模型，量化版 |
| text_encoder | 16 GB | 文本编码 |
| video VAE | 5.2 GB | 视频编解码 |
| audio VAE | 0.6 GB | 音频编解码 |

**模型路径**: ~/Qwen3.8-27B/models/NVFP4/ (diffusion model)
**注意**: 没有 SD/SDXL 模型，只有 H3 视频模型。文生图通过生成5帧视频取中间帧实现。

## Qwen3.8-27B (LLM)

| 项目 | 值 |
|------|-----|
| 推理引擎 | SGLang 0.5.18 |
| 量化 | NVFP4 (21GB) |
| 端口 | 8000 (127.0.0.1) |
| 共存模式 | mem-fraction-static=0.55 |
| 独立模式 | mem-fraction-static=0.95 |
| 速度 | ~23 tok/s (NVFP4) |

## 服务端口

| 端口 | 服务 |
|------|------|
| 8000 | SGLang (Qwen3.8-27B) |
| 8188 | ComfyUI |
| 7860 | Qwen-Agent (Gradio) |
| 3000 | Open WebUI |

## GPU 内存协调

ComfyUI 占用约 32GB，与 SGLang 共存时需降低 mem-fraction-static 到 0.55。
启动顺序：停 ComfyUI → 启 SGLang → 启 ComfyUI（由 start_all_services.sh 自动处理）。

## 工作流（本地组，唯一实际使用）

| 语义 | 实现 | 执行方式 | 说明 |
|------|------|----------|------|
| t2v | 内置生成器 / video_minimax_h3_t2v.json | 本地 GPU | 文生视频 |
| i2v | video_minimax_h3_i2v.json | 本地 GPU | 首帧图生视频 |
| r2v | video_minimax_h3_r2v.json | 本地 GPU | 多参考图生视频 |
| flf2v | video_minimax_h3_flf2v.json | 本地 GPU | 首末帧生视频 |

- 全部本地推理，无需任何云登录。
- 云端 `api_minimax_h3_*`（Comfy 登录）**不在使用范围**，不提、不调用。
- 只改动本地镜像（`workflows/remote_workflows/`）；spark 平台
  `~/ai/ComfyUI/user/default/workflows/` 中的同事工作流**永不修改**。
