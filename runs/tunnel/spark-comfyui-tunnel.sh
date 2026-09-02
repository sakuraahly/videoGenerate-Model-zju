#!/bin/bash
# Auto-reconnecting SSH tunnel: local 8188 -> spark 127.0.0.1:8188 (ComfyUI).
# Stops on SIGTERM/SIGINT. Stop with: pkill -f 'spark-comfyui-tunnel'
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/tunnel.log"

cleanup() { echo "[$(date '+%F %T')] wrapper exiting" >> "$LOG"; exit 0; }
trap cleanup TERM INT

echo "[$(date '+%F %T')] tunnel wrapper started (pid $$)" >> "$LOG"
while true; do
  echo "[$(date '+%F %T')] starting ssh tunnel..." >> "$LOG"
  ssh \
    -o ConnectTimeout=15 \
    -o ServerAliveInterval=10 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o TCPKeepAlive=yes \
    -N \
    -L 8188:localhost:8188 \
    spark >> "$LOG" 2>&1
  RC=$?
  echo "[$(date '+%F %T')] ssh exited (rc=$RC), sleeping 2s..." >> "$LOG"
  sleep 2
done
