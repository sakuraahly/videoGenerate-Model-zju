#!/usr/bin/env bash
# Download Qwen/Qwen3.8-27B from ModelScope into ~/Qwen3.8-27B on the DGX Spark.
#
# Usage (paste this whole block into an SSH session to spark, or scp this
# script over and run it):
#   bash ~/download_qwen3.8_27b.sh
#
# Recommended: run inside a tmux session so it survives NAT disconnects.
#   tmux new -s qwen-dl
#   bash ~/download_qwen3.8_27b.sh
#
# Reuses ~/dl-venv (already has `modelscope` installed from the H3 download).

set -euo pipefail

MODEL="Qwen/Qwen3.8-27B"
DEST="$HOME/Qwen3.8-27B"
VENV="$HOME/dl-venv"
LOG="$HOME/Qwen3.8-27B.download.log"
WORKERS=8

if [ ! -d "$VENV" ]; then
  echo "ERROR: $VENV not found. Install modelscope first:"
  echo "  python3 -m venv $VENV"
  echo "  $VENV/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple modelscope"
  exit 1
fi

mkdir -p "$DEST"
echo "[$(date -Iseconds)] starting download of $MODEL into $DEST" | tee -a "$LOG"

# Use the Python SDK for robust resumable download with parallel workers.
"$VENV/bin/python" - <<PY 2>&1 | tee -a "$LOG"
from modelscope import snapshot_download
path = snapshot_download(
    "$MODEL",
    cache_dir="$DEST",
    max_workers=$WORKERS,
)
print("downloaded to:", path)
PY

echo "[$(date -Iseconds)] done" | tee -a "$LOG"
ls -la "$DEST"
