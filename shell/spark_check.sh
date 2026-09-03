#!/usr/bin/env bash
# Check tools and disk on spark, then start download of Qwen3.8-27B into ~/Qwen3.8-27B
set -u

echo "=== tools ==="
which modelscope || true
which huggingface-cli || true
ls ~/dl-venv/bin/modelscope 2>/dev/null && echo "dl-venv modelscope available"
echo "=== disk ==="
df -h ~ | tail -3
echo "=== existing ==="
ls -la ~/Qwen3.8-27B 2>/dev/null | head -5 || echo "no ~/Qwen3.8-27B yet"
