#!/usr/bin/env bash
# Spark 全服务协调启动脚本
# 解决 SGLang 模型加载与 ComfyUI 的内存竞争问题
#
# 启动顺序：
#   1. 停 ComfyUI（释放 GPU 内存给 SGLang 加载）
#   2. 启动 SGLang（等待模型加载完成）
#   3. 启动 ComfyUI（SGLang 加载完毕后内存够用）
#   4. 启动 qwen-agent + Open WebUI
#
# Usage:
#   bash start_all_services.sh           # 全启动
#   bash start_all_services.sh --no-comfy  # 不启动 ComfyUI
set -euo pipefail

COMFYUI_TMUX="comfyui"
COMFYUI_DIR="$HOME/ai/ComfyUI"
SGLANG_MODEL="$HOME/Qwen3.8-27B/models/NVFP4"
SGLANG_VENV="$HOME/Qwen3.8-27B/sglang-venv"
SGLANG_PORT=8000
SGLANG_MEM="${SGLANG_MEM:-0.55}"
START_COMFYUI=true

for arg in "$@"; do
    case "$arg" in
        --no-comfy) START_COMFYUI=false ;;
    esac
done

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── Step 1: Stop ComfyUI ──────────────────────────────────────────
if [ "$START_COMFYUI" = true ]; then
    log "Stopping ComfyUI (free GPU memory for SGLang loading)..."
    if tmux has-session -t "$COMFYUI_TMUX" 2>/dev/null; then
        tmux send-keys -t "$COMFYUI_TMUX" C-c
        sleep 3
        tmux kill-session -t "$COMFYUI_TMUX" 2>/dev/null || true
        log "ComfyUI stopped"
    else
        log "ComfyUI not running"
    fi
    # Also kill any stray ComfyUI processes
    pkill -f "main.py.*--port 8188" 2>/dev/null || true
    sleep 2
fi

# ── Step 2: Start SGLang ──────────────────────────────────────────
log "Starting SGLang (mem=$SGLANG_MEM, coexist mode)..."
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export TRITON_PTXAS_PATH="${CUDA_HOME}/bin/ptxas"
export MAX_JOBS=2

# Kill any existing SGLang
pkill -f "sglang.launch_server" 2>/dev/null || true
sleep 2

# Start in tmux session
tmux new-session -d -s sglang \
    "source $SGLANG_VENV/bin/activate && \
     python -m sglang.launch_server \
       --model-path $SGLANG_MODEL \
       --served-model-name Qwen3.8-27B \
       --host 127.0.0.1 --port $SGLANG_PORT \
       --tp-size 1 --mem-fraction-static $SGLANG_MEM \
       --context-length 32768 --chunked-prefill-size 8192 \
       --disable-prefill-cuda-graph --trust-remote-code \
       --speculative-algorithm NEXTN --speculative-num-steps 3 \
       --speculative-eagle-topk 1 --speculative-num-draft-tokens 4 \
     2>&1 | tee $HOME/Qwen3.8-27B/sglang.log"

log "Waiting for SGLang to load model (typically 2-3 min)..."
for i in $(seq 1 300); do
    if curl -sf "http://127.0.0.1:$SGLANG_PORT/v1/models" >/dev/null 2>&1; then
        log "SGLang ready! (${i}s)"
        break
    fi
    if [ "$i" -eq 300 ]; then
        log "ERROR: SGLang failed to start within 300s"
        exit 1
    fi
    sleep 1
done

# ── Step 3: Start ComfyUI ─────────────────────────────────────────
if [ "$START_COMFYUI" = true ]; then
    log "Starting ComfyUI..."
    tmux new-session -d -s "$COMFYUI_TMUX" \
        "cd $COMFYUI_DIR && source $HOME/ai/venv/bin/activate && \
         python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 12 --enable-manager 2>&1 | tee $HOME/comfyui.log"
    # Wait for ComfyUI
    for i in $(seq 1 60); do
        if curl -sf http://127.0.0.1:8188/ >/dev/null 2>&1; then
            log "ComfyUI ready! (${i}s)"
            break
        fi
        if [ "$i" -eq 60 ]; then
            log "WARN: ComfyUI not ready after 60s (may still be loading)"
        fi
        sleep 1
    done
fi

# ── Step 4: Start qwen-agent + Open WebUI ─────────────────────────
log "Starting qwen-agent..."
tmux new-session -d -s qwen-agent \
    "source $HOME/qwen-agent-venv/bin/activate && \
     cd $HOME/videoGenerate-Model-zju && \
     python3 $HOME/Qwen3.8-27B/start_qwen_agent.py --port 7860 \
     2>&1 | tee $HOME/qwen-agent.log"

log "Starting Open WebUI (RAG enabled)..."
tmux new-session -d -s webui \
    "source $HOME/open-webui-venv2/bin/activate && \
     HF_HUB_OFFLINE=1 \
     OPENAI_API_BASE_URL=http://127.0.0.1:$SGLANG_PORT/v1 \
     open-webui serve --host 0.0.0.0 --port 3000 \
     2>&1 | tee $HOME/webui.log"

sleep 5

# ── Status ─────────────────────────────────────────────────────────
log "=== All services status ==="
for s in sglang "$COMFYUI_TMUX" qwen-agent webui; do
    if tmux has-session -t "$s" 2>/dev/null; then
        printf "  %-15s ACTIVE\n" "$s"
    else
        printf "  %-15s NOT RUNNING\n" "$s"
    fi
done
for port in 8000 8188 7860 3000; do
    if ss -ltn 2>/dev/null | grep -q ":$port "; then
        printf "  :%-5s UP\n" "$port"
    else
        printf "  :%-5s DOWN\n" "$port"
    fi
done
log "Done!"
