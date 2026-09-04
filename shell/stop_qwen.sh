#!/usr/bin/env bash
# 停止 Qwen 系列服务（SGLang / Qwen-Agent / Open WebUI），不碰 ComfyUI
#
# 用法:
#   bash shell/stop_qwen.sh           # 停止 Qwen 三件套
#   bash shell/stop_qwen.sh --status  # 仅查看状态（全部 4 个服务）
#
# 安全保证: 绝不 kill ComfyUI 进程、不动 tmux comfyui 会话
set -euo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── Status ─────────────────────────────────────────────────────────
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

# ── Stop Qwen services only ──────────────────────────────────────
stop_qwen() {
    log "停止 SGLang (端口 8000)..."
    if tmux has-session -t sglang 2>/dev/null; then
        tmux send-keys -t sglang C-c 2>/dev/null || true
        sleep 2
        tmux kill-session -t sglang 2>/dev/null || true
        log "  tmux 会话 sglang 已关闭"
    else
        log "  tmux 会话 sglang 不存在"
    fi
    pkill -f "sglang.launch_server" 2>/dev/null || true

    log "停止 Qwen-Agent (端口 7860)..."
    if tmux has-session -t qwen-agent 2>/dev/null; then
        tmux send-keys -t qwen-agent C-c 2>/dev/null || true
        sleep 1
        tmux kill-session -t qwen-agent 2>/dev/null || true
        log "  tmux 会话 qwen-agent 已关闭"
    else
        log "  tmux 会话 qwen-agent 不存在"
    fi

    log "停止 Open WebUI (端口 3000)..."
    if tmux has-session -t webui 2>/dev/null; then
        tmux send-keys -t webui C-c 2>/dev/null || true
        sleep 1
        tmux kill-session -t webui 2>/dev/null || true
        log "  tmux 会话 webui 已关闭"
    else
        log "  tmux 会话 webui 不存在"
    fi

    log "Qwen 服务已全部停止（ComfyUI 未受影响）"
}

# ── Main ──────────────────────────────────────────────────────────
case "${1:-}" in
    --status)
        show_status
        ;;
    *)
        stop_qwen
        echo
        show_status
        ;;
esac
