# Qwen(SGLang) 内存占用优化与“生成期让位”设计

> 目标平台：DGX Spark (GB10, aarch64)，**统一内存池 ~121GB 可用**（GPU/CPU 共享，
> 无独立显存概念）。本文汇总：① 已部署的优化方法（仓库与 spark
> `~/Qwen3.8-27B/` 文档：DEPLOYMENT.md / PROJECT-STATUS.md / docs/local-model*）；
> ② 本轮进一步优化与运行时让位（nap/wake）；③ 效果与操作。

## 1. 已部署的优化方法（盘点）

| 优化 | 内容 | 效果 |
|---|---|---|
| NVFP4 量化（RadixArk） | MLP=NVFP4、Attn=FP8、Vision/MTP=BF16；模型在 `~/Qwen3.8-27B/models/NVFP4/` | bf16 51GB → **21GB** |
| SGLang 引擎（0.5.18） | 替代 vLLM；aarch64 wheel；23 tok/s(NVFP4) vs vLLM 17.8 | 速度约 +30~40% |
| 共存内存比例 | SGLang `--mem-fraction-static 0.55` coexist / 0.95 standalone | 与 ComfyUI 同驻 |
| 上下文长度 | `--context-length 32768`；chunked-prefill 8192 | 长文支持 |
| 预填充优化 | `--disable-prefill-cuda-graph` | TTFT 降 ~47% |
| 投机解码 | NEXTN（3 步/eagle topk1/draft 4） | 加速（Qwen3.5 MTP） |
| vLLM 备用路径 | max-model-len 16384、gpu-mem 0.88 standalone / 0.55 coexist、`--limit-mm-per-prompt '{"image":4,"video":2}'` | 与 smart_start 避让 ComfyUI |
| FlashInfer SM12.1 | 已装 0.6.16.post3，但 fp8 KV kernel 未适配 → 回退 FlashAttention v2 | fp8 KV 待官方修复（跟踪 GitHub issue） |
| 其它候选（文档记录） | GGUF Q4_K_M 17GB/21.4 tok/s（llama.cpp）、FP8 29GB 等 | 未启用（NVFP4+SGLang 最优） |

## 2. 内存账本（实测口径 2026-09）

统一内存总量 ~121GB（free 显示 121G）。**ComfyUI 常驻约 49GB RSS**（H3 权重 + reserve-vram 12 + 框架开销），生成峰值再加少量 latent；空闲时可 `POST /free {unload_models:true, free_memory:true}` 卸载其已加载权重（实测 49GB→18GB，服务不动）。

**实测修正（重要经验）**：SGLang 的模型预加载（NVFP4 权重 + 混合注意力状态等）约 **49GB**——mem-fraction 0.40（≈48GB 预算）必然失败（`max_mamba_cache_size` 为负）；且启动依赖 flashinfer JIT（需 `ninja` 在 PATH，已在启动脚本前置 `sglang-venv/bin`）。因此 coexist 默认取 **mem 0.50 / ctx 8192**（实测 120s 就绪、可用）。

| 组合 | SGLang 份额 | 估算占用 | 是否可行 |
|---|---|---|---|
| 旧默认（已废弃） | mem 0.55 + ctx 32768 | 预载 49 + 大 KV 池 ≈ 76GB+ | 与 ComfyUI 49GB 叠加超载 ❌ |
| mem 0.40（试过） | ctx 16384 | 预算 48GB < 预载 49GB | ❌ KV 池分配直接失败 |
| **新默认（已验证）** | mem **0.50** + ctx **8192** | 预载 49 + 小 KV 池 ≈ 50-55GB | ✅ 120s 就绪；与 ComfyUI 空闲(/free 后 18GB)共存有余量 |
| nap（生成期） | 停止 SGLang | ~0 | ✅ ComfyUI 独占/最快 |
| standalone | mem 0.95 | ≈115GB | 仅 ComfyUI 完全停止时用 |

## 3. 本轮新增：运行时让位（nap/wake）+ 降额默认

代码：`runs/agent/llm_mem.py`（spark 侧执行）；界面/CLI 自动接线（ui_app.py /
scheduler.py）；配置 `config/llm_mem.json`（机器配置，示例 `.example`）：
`{"enabled": true, "mem_fraction": 0.50, "context_length": 8192}`

- **降额默认**：`shell/start_sglang_coexist.sh`、`spark_sglang_start.sh`、
  `start_all_services.sh` 的 coexist 默认改为 **mem 0.50 / ctx 8192**，并在启动
  前把 `sglang-venv/bin` 前置到 PATH（flashinfer JIT 需要 ninja）。
- **自动让位**：agent 回合文本出现 `TASK_SUBMITTED:`（真实生成任务已提交、非 dry_run）
  → 回合安全结束后自动 `nap()`（优雅停 SGLang，释放 ~40-60GB 给 ComfyUI）；
- **自动唤醒**：下一轮对话开始 `ensure_llm_up()` 检测 8000 未就绪 → `wake()`
  （以 llm_mem 配置降额启动并轮询 /v1/models，典型 1-3 分钟），期间界面状态栏
  持续显示“正在唤醒本地模型…”，agent 工作不中断。

命令（人工/脚本）：
```bash
python3 runs/agent/llm_mem.py status
python3 runs/agent/llm_mem.py nap     # 让位（不动 ComfyUI/agent 进程）
python3 runs/agent/llm_mem.py wake    # 恢复（读 llm_mem.json 的降额配置）
python3 runs/agent/llm_mem.py flush   # 运行时清 KV 缓存（可选）
```

## 4. 不触碰边界
- nap/wake 只作用于 SGLang（tmux `sglang` / `sglang.launch_server` 进程）；
  **不触碰 ComfyUI(systemd comfyui.service) 与 agent/OpenWebUI 等其它服务**。
- 未使用 GPU 独占模式启动时请勿与 ComfyUI 同开（0.95 只用于 ComfyUI 停止后）。

## 5. 参考
- 仓库：`docs/local-model/quick-start.md`、`docs/local-model/full-manual.md`、
  `docs/qwen38-deployment.md`、`docs/session-summary.md §10/§11`
- spark：`~/Qwen3.8-27B/DEPLOYMENT.md`、`~/Qwen3.8-27B/PROJECT-STATUS.md`
- 内核问题：FlashInfer fp8-KV SM12.1（https://github.com/flashinfer-ai/flashinfer/issues）
