#!/usr/bin/env bash
# Start SGLang server for Qwen3.8-27B on DGX Spark.
# SGLang is ~40% faster than vLLM on GB10 with FlashInfer backend.
#
# Usage:
#   bash start_sglang.sh                          # standalone (NVFP4 model)
#   bash start_sglang.sh --bf16                    # use bf16 model instead
#   SGLANG_PORT=8001 SGLANG_MEM=0.88 bash start_sglang.sh
set -euo pipefail

VENV="$HOME/Qwen3.8-27B/sglang-venv"
NVFP4_MODEL="$HOME/Qwen3.8-27B/models/NVFP4"
BF16_MODEL="$HOME/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master"

HOST="${SGLANG_HOST:-127.0.0.1}"
PORT="${SGLANG_PORT:-8000}"
MEM="${SGLANG_MEM:-0.95}"
TP="${SGLANG_TP:-1}"
CTX_LEN="${SGLANG_CTX_LEN:-32768}"
CHUNK_SIZE="${SGLANG_CHUNK_SIZE:-8192}"

USE_NVFP4=true
for arg in "$@"; do
    case "$arg" in
        --bf16) USE_NVFP4=false ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$USE_NVFP4" = true ] && [ -d "$NVFP4_MODEL" ] && [ "$(ls -A "$NVFP4_MODEL" 2>/dev/null)" ]; then
    MODEL_PATH="$NVFP4_MODEL"
    PROFILE="nvfp4"
else
    MODEL_PATH="$BF16_MODEL"
    PROFILE="bf16"
    echo "[INFO] NVFP4 model not found, falling back to bf16"
fi

echo "=== SGLang server starting ==="
echo "  model:     $MODEL_PATH"
echo "  profile:   $PROFILE"
echo "  listen:    $HOST:$PORT"
echo "  tp:        $TP"
echo "  mem:       $MEM"
echo "  ctx_len:   $CTX_LEN"
echo "  chunk:     $CHUNK_SIZE"
echo "=============================="

export PATH="$VENV/bin:$PATH"

exec "$VENV/bin/python" -m sglang.launch_server \
    --model-path "$MODEL_PATH" \
    --host "$HOST" \
    --port "$PORT" \
    --tp "$TP" \
    --mem-fraction-static "$MEM" \
    --context-length "$CTX_LEN" \
    --chunked-prefill-size "$CHUNK_SIZE" \
    --disable-prefill-cuda-graph \
    --trust-remote-code \
    --dtype bfloat16
