#!/usr/bin/env bash
# Start vLLM OpenAI-compatible API server for Qwen3.8-27B on DGX Spark.
# Run inside tmux:  tmux new -s vllm && bash ~/Qwen3.8-27B/start_vllm.sh
#
# Override defaults via env vars:
#   VLLM_PORT=8000  VLLM_MAX_LEN=16384  VLLM_GPU_MEM=0.88  bash start_vllm.sh
set -euo pipefail

VENV="$HOME/Qwen3.8-27B/vllm-venv"
MODEL_PATH="$HOME/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master"
HOST="${VLLM_HOST:-127.0.0.1}"
PORT="${VLLM_PORT:-8000}"
SERVED_NAME="${VLLM_MODEL_NAME:-Qwen3.8-27B}"
TP="${VLLM_TP:-1}"
MAX_MODEL_LEN="${VLLM_MAX_LEN:-16384}"
GPU_MEM="${VLLM_GPU_MEM:-0.88}"
KV_DTYPE="${VLLM_KV_DTYPE:-auto}"

export PATH="$VENV/bin:$PATH"
export VLLM_ALLOW_LONG_MAX_MODEL_LEN="${VLLM_ALLOW_LONG_MAX_MODEL_LEN:-1}"

echo "=== vLLM server starting ==="
echo "  model:     $MODEL_PATH"
echo "  listen:    $HOST:$PORT"
echo "  served-as: $SERVED_NAME"
echo "  tp:        $TP"
echo "  max_len:   $MAX_MODEL_LEN"
echo "  gpu_mem:   $GPU_MEM"
echo "  kv_dtype:  $KV_DTYPE"
echo "==========================="

exec "$VENV/bin/python" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --host "$HOST" \
    --port "$PORT" \
    --tensor-parallel-size "$TP" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEM" \
    --kv-cache-dtype "$KV_DTYPE" \
    --trust-remote-code \
    --dtype bfloat16 \
    --limit-mm-per-prompt '{"image": 4, "video": 2}'
