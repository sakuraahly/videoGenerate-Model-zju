#!/usr/bin/env bash
# 仅保留 ComfyUI，停止所有 Qwen 相关服务
# 用法:
#   bash shell/comfyui_only.sh          # 停 Qwen 三件套，保/启 ComfyUI
#   bash shell/comfyui_only.sh --stop   # 停全部（含 ComfyUI）
#   bash shell/comfyui_only.sh --status # 仅查看状态
set -euo pipefail

COMFYUI_TMUX="comfyui"
COMFYUI_DIR="$HOME/ai/ComfyUI"
COMFYUI_PORT=8188

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── Status only ────────────────────────────────────────────────────
show_status() {
    echo "=== tmux 会话 ==="
    tmux ls 2>&1 || echo "  (无)"
    echo
    echo "=== 端口 ==="
    for pair in "SGLang:8000" "ComfyUI:8188" "Qwen-Agent:7860" "OpenWebUI:3000"; do
        name="${pair%%:*}"
        port="${pair##*:}"
        if ss -ltn 2>/dev/null | grep -q ":$port "; then
            printf "  %-15s :%-5s UP\n" "$name" "$port"
        else
            printf "  %-15s :%-5s DOWN\n" "$name" "$port"
        fi
    done
}

# ── Stop Qwen services ────────────────────────────────────────────
stop_qwen() {
    log "停止 SGLang..."
    if tmux has-session -t sglang 2>/dev/null; then
        tmux send-keys -t sglang C-c 2>/dev/null || true
        sleep 2
        tmux kill-session -t sglang 2>/dev/null || true
    fi
    pkill -f "sglang.launch_server" 2>/dev/null || true

    log "停止 Qwen-Agent..."
    if tmux has-session -t qwen-agent 2>/dev/null; then
        tmux send-keys -t qwen-agent C-c 2>/dev/null || true
        sleep 1
        tmux kill-session -t qwen-agent 2>/dev/null || true
    fi

    log "停止 Open WebUI..."
    if tmux has-session -t webui 2>/dev/null; then
        tmux send-keys -t webui C-c 2>/dev/null || true
        sleep 1
        tmux kill-session -t webui 2>/dev/null || true
    fi

    log "Qwen 服务已全部停止"
}

# ── Start ComfyUI ─────────────────────────────────────────────────
start_comfyui() {
    if ss -ltn 2>/dev/null | grep -q ":$COMFYUI_PORT "; then
        log "ComfyUI 已在运行 (端口 $COMFYUI_PORT)"
        return 0
    fi

    log "启动 ComfyUI..."
    tmux new-session -d -s "$COMFYUI_TMUX" \
        "cd $COMFYUI_DIR && source $HOME/ai/venv/bin/activate && \
         python main.py --listen 127.0.0.1 --port $COMFYUI_PORT \
         --disable-auto-launch --reserve-vram 12 --enable-manager \
         2>&1 | tee $HOME/comfyui.log"

    for i in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:$COMFYUI_PORT/" >/dev/null 2>&1; then
            log "ComfyUI 就绪! (${i}s)"
            return 0
        fi
        sleep 1
    done
    log "WARN: ComfyUI 60s 内未就绪（可能仍在加载）"
}

# ── Stop all ──────────────────────────────────────────────────────
stop_all() {
    stop_qwen
    log "停止 ComfyUI..."
    if tmux has-session -t "$COMFYUI_TMUX" 2>/dev/null; then
        tmux send-keys -t "$COMFYUI_TMUX" C-c 2>/dev/null || true
        sleep 2
        tmux kill-session -t "$COMFYUI_TMUX" 2>/dev/null || true
    fi
    pkill -f "main.py.*--port $COMFYUI_PORT" 2>/dev/null || true
    log "全部服务已停止"
}

# ── Main ──────────────────────────────────────────────────────────
case "${1:-}" in
    --stop)
        stop_all
        ;;
    --status)
        show_status
        ;;
    *)
        stop_qwen
        start_comfyui
        echo
        show_status
        log "完成 — 仅 ComfyUI 运行"
        ;;
esac
