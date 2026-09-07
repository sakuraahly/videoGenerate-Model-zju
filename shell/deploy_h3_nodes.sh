#!/bin/bash
# 部署 H3 成品链节点到 ComfyUI custom_nodes（ComfyUI 下次重启后生效）
set -e
REPO=/home/Developer/videoGenerate-Model-zju
DEST=~/ai/ComfyUI/custom_nodes/h3_finalize
mkdir -p "$DEST"
cp "$REPO/comfy_nodes/h3_finalize/__init__.py" "$DEST/"
echo "deployed -> $DEST"
ls -la "$DEST"