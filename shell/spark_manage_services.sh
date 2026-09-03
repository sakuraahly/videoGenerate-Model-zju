#!/usr/bin/env bash
# Service manager for Qwen3.8-27B inference engines + ComfyUI on DGX Spark.
# Usage: bash manage_services.sh <command>
#
# Commands:
#   status          Show status of all services
#   start-vllm      Start vLLM (smart mode — auto-detects ComfyUI)
#   stop-vllm       Stop vLLM
#   start-sglang    Start SGLang (recommended engine, ~40% faster on GB10)
#   stop-sglang     Stop SGLang
#   start-comfyui   Start ComfyUI
#   stop-comfyui    Stop ComfyUI
#   stop-all        Stop all services
#   health          Quick health check (returns exit code)
#   gpu             Show GPU memory breakdown
set -euo pipefail

CMD="${1:-status}"

vllm_running() {
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health 2>/dev/null | grep -q 200
}

comfyui_running() {
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8188 2>/dev/null | grep -q 200
}

sglang_running() {
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health 2>/dev/null | grep -q 200
}

show_gpu() {
    echo "=== GPU Processes ==="
    nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi not available)"
    echo ""
    echo "=== GPU Overview ==="
    nvidia-smi 2>/dev/null | head -25 || echo "  (nvidia-smi not available)"
}

case "$CMD" in
    status)
        echo "=== DGX Spark Services ==="
        echo ""
        if vllm_running; then
            echo "  vLLM (Qwen3.8-27B):  RUNNING  http://127.0.0.1:8000"
        else
            echo "  vLLM (Qwen3.8-27B):  STOPPED"
        fi
        if sglang_running; then
            echo "  SGLang:              RUNNING  http://127.0.0.1:8000"
        else
            echo "  SGLang:              STOPPED"
        fi
        if comfyui_running; then
            echo "  ComfyUI:             RUNNING  http://127.0.0.1:8188"
        else
            echo "  ComfyUI:             STOPPED"
        fi
        echo ""
        echo "=== tmux sessions ==="
        tmux list-sessions 2>/dev/null || echo "  (no sessions)"
        echo ""
        show_gpu
        ;;

    start-vllm)
        if vllm_running; then
            echo "[OK] vLLM is already running."
            exit 0
        fi
        echo "Starting vLLM (smart mode)..."
        bash "$(dirname "$0")/smart_start_vllm.sh"
        ;;

    stop-vllm)
        echo "Stopping vLLM..."
        tmux send-keys -t vllm C-c 2>/dev/null || true
        sleep 3
        tmux kill-session -t vllm 2>/dev/null || true
        pkill -f "vllm.entrypoints" 2>/dev/null || true
        pkill -f "EngineCore" 2>/dev/null || true
        sleep 2
        if vllm_running; then
            echo "[WARN] vLLM may still be shutting down..."
        else
            echo "[OK] vLLM stopped."
        fi
        ;;

    start-sglang)
        if sglang_running; then
            echo "[OK] SGLang is already running."
            exit 0
        fi
        if vllm_running; then
            echo "[ERROR] vLLM is running on port 8000. Stop it first: $0 stop-vllm"
            exit 1
        fi
        echo "Starting SGLang..."
        tmux new-session -d -s sglang \
            "bash $(dirname "$0")/start_sglang.sh 2>&1 | tee ~/sglang-serve.log"
        echo "Waiting for SGLang to become ready..."
        for i in $(seq 1 60); do
            if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health 2>/dev/null | grep -q 200; then
                echo "[OK] SGLang is READY (took ~$((i * 5))s)"
                exit 0
            fi
            sleep 5
            printf "."
        done
        echo ""
        echo "[WARN] SGLang did not become ready within 5 minutes."
        echo "       Check logs: tail -50 ~/sglang-serve.log"
        ;;

    stop-sglang)
        echo "Stopping SGLang..."
        tmux send-keys -t sglang C-c 2>/dev/null || true
        sleep 3
        tmux kill-session -t sglang 2>/dev/null || true
        pkill -f "sglang.launch_server" 2>/dev/null || true
        sleep 2
        if sglang_running; then
            echo "[WARN] SGLang may still be shutting down..."
        else
            echo "[OK] SGLang stopped."
        fi
        ;;

    start-comfyui)
        if comfyui_running; then
            echo "[OK] ComfyUI is already running."
            exit 0
        fi
        echo "Starting ComfyUI..."
        tmux new-session -d -s comfyui \
            "cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 12 2>&1 | tee ~/comfyui.log"
        sleep 5
        if comfyui_running; then
            echo "[OK] ComfyUI is running at http://127.0.0.1:8188"
        else
            echo "[WARN] ComfyUI may still be starting. Check: tail -20 ~/comfyui.log"
        fi
        ;;

    stop-comfyui)
        echo "Stopping ComfyUI..."
        tmux kill-session -t comfyui 2>/dev/null || true
        pkill -f "ComfyUI\|comfyui" 2>/dev/null || true
        sleep 2
        echo "[OK] ComfyUI stopped."
        ;;

    stop-all)
        echo "Stopping all services..."
        bash "$0" stop-vllm
        bash "$0" stop-sglang
        bash "$0" stop-comfyui
        echo "[OK] All services stopped."
        ;;

    health)
        EXIT=0
        if vllm_running || sglang_running; then
            echo "[OK] Inference engine: healthy"
        else
            echo "[FAIL] Inference engine: not responding"
            EXIT=1
        fi
        if comfyui_running; then
            echo "[OK] ComfyUI: healthy"
        else
            echo "[INFO] ComfyUI: not running"
        fi
        exit $EXIT
        ;;

    gpu)
        show_gpu
        ;;

    *)
        echo "Usage: $0 {status|start-vllm|stop-vllm|start-sglang|stop-sglang|start-comfyui|stop-comfyui|stop-all|health|gpu}"
        exit 1
        ;;
esac
