#!/usr/bin/env bash
# Spark AI 服务管理 — 启动/停止/查看 SGLang + ComfyUI + Qwen-Agent + Open WebUI
#
# Usage:
#   bash manage_services.sh start      # 协调启动全部服务（先停 ComfyUI → 加载 SGLang → 再启 ComfyUI）
#   bash manage_services.sh stop       # 停止所有服务
#   bash manage_services.sh restart    # 重启所有服务
#   bash manage_services.sh status     # 查看服务状态
#   bash manage_services.sh logs       # 查看最近日志
#   bash manage_services.sh enable     # 启用开机自启
#   bash manage_services.sh disable    # 禁用开机自启
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART_FILE="$HOME/.config/autostart/spark-ai-services.desktop"

do_start() {
    echo "=== 协调启动所有服务 ==="
    bash "$SCRIPT_DIR/start_all_services.sh"
}

do_stop() {
    echo "停止所有服务..."
    for session in webui qwen-agent sglang comfyui; do
        if tmux has-session -t "$session" 2>/dev/null; then
            tmux kill-session -t "$session"
            echo "  stopped: $session"
        fi
    done
    pkill -f "sglang.launch_server" 2>/dev/null || true
    pkill -f "open-webui serve" 2>/dev/null || true
    pkill -f "start_qwen_agent" 2>/dev/null || true
    sleep 2
    echo "[OK] 所有服务已停止"
}

do_restart() {
    do_stop
    sleep 2
    do_start
}

do_status() {
    echo "=== tmux 会话 ==="
    for session in sglang comfyui qwen-agent webui; do
        if tmux has-session -t "$session" 2>/dev/null; then
            printf "  %-15s \033[32mACTIVE\033[0m\n" "$session"
        else
            printf "  %-15s \033[31mSTOPPED\033[0m\n" "$session"
        fi
    done
    echo ""
    echo "=== 端口 ==="
    declare -A PORTS=(["SGLang"]=8000 ["ComfyUI"]=8188 ["Qwen-Agent"]=7860 ["OpenWebUI"]=3000)
    for name in SGLang ComfyUI Qwen-Agent OpenWebUI; do
        port=${PORTS[$name]}
        if ss -ltn 2>/dev/null | grep -q ":$port "; then
            printf "  %-12s :%-5s \033[32mUP\033[0m\n" "$name" "$port"
        else
            printf "  %-12s :%-5s \033[31mDOWN\033[0m\n" "$name" "$port"
        fi
    done
    echo ""
    echo "=== 开机自启 ==="
    if [ -f "$AUTOSTART_FILE" ]; then
        echo "  已启用 ($AUTOSTART_FILE)"
    else
        echo "  未启用"
    fi
    echo ""
    echo "=== GPU 内存 ==="
    nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi unavailable)"
}

do_enable() {
    mkdir -p "$HOME/.config/autostart"
    cat > "$AUTOSTART_FILE" << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=Spark AI Services (SGLang + ComfyUI + Qwen-Agent + Open WebUI)
Exec=bash -c "sleep 5 && exec $HOME/videoGenerate-Model-zju/shell/start_all_services.sh >> $HOME/service-boot.log 2>&1"
X-GNOME-Autostart-enabled=true
Comment=Auto-start AI services on DGX Spark boot
DESKTOP
    echo "[OK] 已启用开机自启"
    echo "  文件: $AUTOSTART_FILE"
    echo "  脚本: $SCRIPT_DIR/start_all_services.sh"
    echo "  SGLang 模式: coexist (mem=0.55)"
}

do_disable() {
    rm -f "$AUTOSTART_FILE"
    echo "[OK] 已禁用开机自启"
}

do_logs() {
    echo "=== SGLang (last 15 lines) ==="
    tail -15 ~/Qwen3.8-27B/sglang.log 2>/dev/null || echo "  (no log)"
    echo ""
    echo "=== ComfyUI (last 10 lines) ==="
    tail -10 ~/comfyui.log 2>/dev/null || echo "  (no log)"
    echo ""
    echo "=== qwen-agent (last 10 lines) ==="
    tail -10 ~/qwen-agent.log 2>/dev/null || echo "  (no log)"
    echo ""
    echo "=== Open WebUI (last 10 lines) ==="
    tail -10 ~/webui.log 2>/dev/null || echo "  (no log)"
    echo ""
    echo "=== 开机日志 (last 20 lines) ==="
    tail -20 ~/service-boot.log 2>/dev/null || echo "  (no log)"
}

case "${1:-help}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    enable)  do_enable ;;
    disable) do_disable ;;
    logs)    do_logs ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|enable|disable|logs}"
        echo ""
        echo "  start    协调启动全部服务（先停 ComfyUI → SGLang 加载 → 再启 ComfyUI）"
        echo "  stop     停止所有服务"
        echo "  restart  重启所有服务"
        echo "  status   查看服务状态 + 端口 + GPU 内存"
        echo "  enable   启用开机自启（XDG autostart）"
        echo "  disable  禁用开机自启"
        echo "  logs     查看最近日志"
        exit 1
        ;;
esac
