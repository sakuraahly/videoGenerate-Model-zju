#!/usr/bin/env bash
# One-shot: start vLLM in tmux on spark, then open terminal chat via SSH tunnel.
# Usage: bash shell/spark_chat_setup.sh
set -euo pipefail

REMOTE="spark"
VENV="$HOME/Qwen3.8-27B/vllm-venv"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Step 1: Copy scripts to spark ==="
scp "$SCRIPT_DIR/spark_vllm_start.sh" "$REMOTE:~/Qwen3.8-27B/start_vllm.sh"
scp "$SCRIPT_DIR/spark_chat_terminal.py" "$REMOTE:~/Qwen3.8-27B/chat_terminal.py"
ssh "$REMOTE" "chmod +x ~/Qwen3.8-27B/start_vllm.sh"
echo "  Scripts copied."

echo ""
echo "=== Step 2: Check if vLLM is already running ==="
if ssh "$REMOTE" "curl -s http://127.0.0.1:8000/v1/models >/dev/null 2>&1"; then
    echo "  vLLM already running on spark:8000"
else
    echo "  Starting vLLM in tmux session 'vllm'..."
    ssh "$REMOTE" "tmux kill-session -t vllm 2>/dev/null || true"
    ssh "$REMOTE" "tmux new-session -d -s vllm 'bash ~/Qwen3.8-27B/start_vllm.sh 2>&1 | tee ~/vllm-server.log'"
    echo "  Waiting for server to be ready..."
    for i in $(seq 1 60); do
        if ssh "$REMOTE" "curl -s http://127.0.0.1:8000/v1/models >/dev/null 2>&1"; then
            echo "  Server ready! (${i}s)"
            break
        fi
        if [ "$i" -eq 60 ]; then
            echo "  Timeout waiting for server. Check: ssh spark 'tmux attach -t vllm'"
            exit 1
        fi
        sleep 5
        printf "."
    done
    echo ""
fi

echo ""
echo "=== Step 3: Open terminal chat ==="
echo "  Connecting to Qwen3.8-27B via SSH..."
echo ""
ssh -t "$REMOTE" "$VENV/bin/python ~/Qwen3.8-27B/chat_terminal.py"
