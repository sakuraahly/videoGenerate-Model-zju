#!/usr/bin/env bash
# SGLang 共存模式启动 — 降低 GPU 内存占用，与 ComfyUI 共享 GB10 统一内存
#
# 默认模式 (coexist):  mem=0.50, ctx=8192（实测预载≈49GB，0.40 不足）；见 docs/llm-memory-optimization.md
# 独占模式 (standalone): mem=0.95, SGLang 独享大部分 GPU 内存
#
# Usage:
#   bash start_sglang_coexist.sh              # 共存模式（默认）
#   bash start_sglang_coexist.sh --standalone  # 独占模式
#   SGLANG_MEM=0.65 bash start_sglang_coexist.sh  # 自定义内存比例
set -euo pipefail

VENV="$HOME/Qwen3.8-27B/sglang-venv"
export PATH="$VENV/bin:$PATH"   # flashinfer JIT(ninja) 与启动器同 PATH
NVFP4_MODEL="$HOME/Qwen3.8-27B/models/NVFP4"
BF16_MODEL="$HOME/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master"

HOST="${SGLANG_HOST:-127.0.0.1}"
PORT="${SGLANG_PORT:-8000}"
TP="${SGLANG_TP:-1}"
CTX_LEN="${SGLANG_CTX_LEN:-8192}"
CHUNK_SIZE="${SGLANG_CHUNK_SIZE:-8192}"
MAX_RUN="${SGLANG_MAX_RUN:-}"   # book-13：共享显存下控制 mamba/linear KV 预算（默认不传）
SPEC="${SGLANG_SPEC:-on}"          # book-16 E1：off=关闭投机解码（复读/假死风险源），默认 on 保持原行为

MODE="coexist"
for arg in "$@"; do
    case "$arg" in
        --standalone) MODE="standalone" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$MODE" = "standalone" ]; then
    MEM="${SGLANG_MEM:-0.95}"
else
    MEM="${SGLANG_MEM:-0.50}"
fi

export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export TRITON_PTXAS_PATH="${CUDA_HOME}/bin/ptxas"
export MAX_JOBS="${MAX_JOBS:-2}"

USE_NVFP4=true
if [ -d "$NVFP4_MODEL" ] && [ "$(ls -A "$NVFP4_MODEL" 2>/dev/null)" ]; then
    MODEL_PATH="$NVFP4_MODEL"
    PROFILE="nvfp4"
else
    MODEL_PATH="$BF16_MODEL"
    PROFILE="bf16"
    echo "[INFO] NVFP4 model not found, falling back to bf16"
fi

echo "=== SGLang server starting ($MODE mode) ==="
echo "  model:     $MODEL_PATH"
echo "  profile:   $PROFILE"
echo "  listen:    $HOST:$PORT"
echo "  tp:        $TP"
echo "  mem:       $MEM"
echo "  ctx_len:   $CTX_LEN"
echo "  mode:      $MODE (coexist=ComfyUI safe, standalone=max perf)"
echo "============================================"

exec "$VENV/bin/python" \
    -m sglang.launch_server \
    --model-path "$MODEL_PATH" \
    --served-model-name Qwen3.8-27B \
    --host "$HOST" \
    --port "$PORT" \
    --tp-size "$TP" \
    --mem-fraction-static "$MEM" \
    --context-length "$CTX_LEN" \
    --chunked-prefill-size "$CHUNK_SIZE" \
    --disable-prefill-cuda-graph \
    --trust-remote-code \
    $( [ -n "$MAX_RUN" ] && echo --max-running-requests \"$MAX_RUN\" ) \
    $( [ "$PROFILE" = "nvfp4" ] && [ "$SPEC" = "on" ] && echo \
        --speculative-algorithm NEXTN \
        --speculative-num-steps 3 \
        --speculative-eagle-topk 1 \
        --speculative-num-draft-tokens 4 )
