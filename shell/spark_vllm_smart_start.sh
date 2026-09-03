#!/usr/bin/env bash
# Smart vLLM launcher — detects GPU state and adjusts parameters automatically.
# Usage: bash smart_start_vllm.sh [--with-comfyui] [--max-len N] [--fp8] [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_SCRIPT="$SCRIPT_DIR/start_vllm.sh"
VENV="$HOME/Qwen3.8-27B/vllm-venv"

WITH_COMFYUI=false
DRY_RUN=false
CUSTOM_MAX_LEN=""
USE_FP8=false

for arg in "$@"; do
    case "$arg" in
        --with-comfyui)  WITH_COMFYUI=true ;;
        --dry-run)       DRY_RUN=true ;;
        --max-len=*)     CUSTOM_MAX_LEN="${arg#*=}" ;;
        --fp8)           USE_FP8=true ;;
        *)               echo "Unknown option: $arg"; exit 1 ;;
    esac
done

comfyui_running() {
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8188 2>/dev/null | grep -q 200
}

echo "======================================"
echo "  Qwen3.8-27B Smart Launcher (GB10)"
echo "======================================"

# --- Check if vLLM is already running ---
if curl -s -o /dev/null -w '' http://127.0.0.1:8000/health 2>/dev/null; then
    echo "[OK] vLLM is already running at http://127.0.0.1:8000"
    echo "     Use 'bash manage_services.sh stop-vllm' to stop it first."
    exit 0
fi

# --- Detect GPU processes ---
GPU_PROCS=$(nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader,nounits 2>/dev/null || true)
TOTAL_GPU_USED=0

if [ -n "$GPU_PROCS" ]; then
    echo ""
    echo "Current GPU processes:"
    while IFS=',' read -r pid name mem; do
        pid=$(echo "$pid" | xargs)
        name=$(echo "$name" | xargs)
        mem=$(echo "$mem" | xargs)
        printf "  PID %-8s %6s MiB  %s\n" "$pid" "$mem" "$name"
        TOTAL_GPU_USED=$((TOTAL_GPU_USED + mem))
    done <<< "$GPU_PROCS"
    echo "  Total GPU memory in use: ${TOTAL_GPU_USED} MiB"
fi

# --- Detect ComfyUI ---
if comfyui_running; then
    WITH_COMFYUI=true
    COMFYUI_PID=$(ss -tlnp 2>/dev/null | grep ':8188' | grep -oP 'pid=\K[0-9]+' || echo "?")
    echo ""
    echo "[INFO] ComfyUI detected (PID $COMFYUI_PID, port 8188) — will coexist"
fi

# --- Calculate optimal parameters ---
TOTAL_GPU_MIB=124500  # GB10 unified memory ~121.69 GiB
MODEL_WEIGHT_MIB=52200  # 27B model in bf16 ~51.1 GiB
OVERHEAD_MIB=5000  # CUDA context + torch.compile etc.

if [ "$WITH_COMFYUI" = true ]; then
    COMFYUI_RESERVE_MIB=42000  # ComfyUI may use up to ~40 GiB
    AVAILABLE_MIB=$((TOTAL_GPU_MIB - MODEL_WEIGHT_MIB - OVERHEAD_MIB - COMFYUI_RESERVE_MIB))
    MAX_LEN="${CUSTOM_MAX_LEN:-8192}"
    GPU_MEM="0.55"
    PROFILE="coexist"
else
    AVAILABLE_MIB=$((TOTAL_GPU_MIB - MODEL_WEIGHT_MIB - OVERHEAD_MIB))
    MAX_LEN="${CUSTOM_MAX_LEN:-32768}"
    GPU_MEM="0.88"
    PROFILE="standalone"
fi

# KV cache dtype: default auto (bf16), opt-in fp8 via --fp8 flag
KV_DTYPE="auto"
if [ "$USE_FP8" = true ]; then
    if "$VENV/bin/python" -c "import flashinfer" 2>/dev/null; then
        KV_DTYPE="fp8"
        echo "[INFO] fp8 KV cache enabled (--fp8)"
    else
        echo "[WARN] --fp8 requested but FlashInfer not installed."
        echo "       Run: bash install_flashinfer.sh"
    fi
else
    if "$VENV/bin/python" -c "import flashinfer" 2>/dev/null; then
        echo "[INFO] FlashInfer available. Use --fp8 to enable fp8 KV cache (experimental on GB10)"
    fi
fi

echo ""
echo "Launch profile: $PROFILE"
echo "  max-model-len:    $MAX_LEN"
echo "  gpu-mem-util:     $GPU_MEM"
echo "  kv-cache-dtype:   $KV_DTYPE"
echo "  estimated usage:  ~$((MODEL_WEIGHT_MIB + OVERHEAD_MIB)) MiB (model + overhead)"

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "[DRY RUN] Would execute:"
    echo "  VLLM_MAX_LEN=$MAX_LEN VLLM_GPU_MEM=$GPU_MEM VLLM_KV_DTYPE=$KV_DTYPE bash $BASE_SCRIPT"
    exit 0
fi

echo ""
echo "Starting vLLM in tmux session 'vllm'..."
echo "  (logs: ~/qwen-serve.log)"
echo ""

# --- Launch ---
tmux new-session -d -s vllm \
    "VLLM_MAX_LEN=$MAX_LEN VLLM_GPU_MEM=$GPU_MEM VLLM_KV_DTYPE=$KV_DTYPE bash $BASE_SCRIPT 2>&1 | tee ~/qwen-serve.log"

echo "Waiting for server to become ready..."
for i in $(seq 1 60); do
    if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health 2>/dev/null | grep -q 200; then
        ELAPSED=$((i * 10))
        echo ""
        echo "============================================"
        echo "  vLLM is READY (took ~${ELAPSED}s)"
        echo "  Profile:  $PROFILE"
        echo "  Context:  $MAX_LEN tokens"
        echo "  KV cache: $KV_DTYPE"
        echo "  API:      http://127.0.0.1:8000"
        echo "  Chat:     python ~/Qwen3.8-27B/chat_terminal.py"
        echo "============================================"
        exit 0
    fi
    sleep 10
    printf "."
done

echo ""
echo "[WARN] Server did not become ready within 10 minutes."
echo "       Check logs: tail -50 ~/qwen-serve.log"
exit 1
