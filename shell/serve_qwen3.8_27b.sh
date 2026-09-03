#!/usr/bin/env bash
# spark 上启动 Qwen3.8-27B（vLLM, OpenAI 兼容 /v1）供本地 AI 桥(idea2prompts)调用。
# 用法（在 spark 上）：bash ~/serve_qwen3.8_27b.sh
# 之后本地需要 8000 隧道：ssh -N -L 8000:127.0.0.1:8000 spark
set -Eeuo pipefail

MODEL_DIR="$HOME/Qwen3.8-27B/models/Qwen--Qwen3.8-27B/snapshots/master"
VENV="$HOME/Qwen3.8-27B/vllm-venv"
PORT="${VLLM_PORT:-8000}"
NAME="Qwen3.8-27B"
MAX_LEN="${VLLM_MAX_LEN:-32768}"
SESSION="qwen-serve"

if [ ! -d "$MODEL_DIR" ]; then
  echo "ERROR: 模型目录不存在: $MODEL_DIR（先跑 download_qwen3.8_27b.sh）"; exit 1
fi
if [ ! -x "$VENV/bin/vllm" ]; then
  echo "ERROR: $VENV/bin/vllm 不存在（先安装: $VENV/bin/pip install vllm）"; exit 1
fi

# 已在跑则跳过
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "服务已在 tmux 会话 $SESSION 中运行（若需重启先 tmux kill-session -t $SESSION）。"
  echo "curl http://127.0.0.1:${PORT}/v1/models 可验证。"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "$VENV/bin/vllm serve '$MODEL_DIR' --served-model-name '$NAME' --host 127.0.0.1 --port $PORT --max-model-len $MAX_LEN --gpu-memory-utilization 0.9 2>&1 | tee -a $HOME/qwen-serve.log"
echo "已在 tmux($SESSION) 启动 vllm serve：model=$NAME port=$PORT"
echo "日志: tail -f ~/qwen-serve.log   重进: tmux attach -t $SESSION"
echo "就绪检查: curl http://127.0.0.1:${PORT}/v1/models"
