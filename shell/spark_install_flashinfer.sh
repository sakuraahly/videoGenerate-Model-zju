#!/usr/bin/env bash
# Install FlashInfer for vLLM on DGX Spark (GB10, aarch64, CUDA 13.0).
# After installation, the smart launcher will auto-detect and enable fp8 KV cache.
#
# Usage: bash install_flashinfer.sh
# Requires: active vLLM virtualenv at ~/Qwen3.8-27B/vllm-venv
set -euo pipefail

VENV="$HOME/Qwen3.8-27B/vllm-venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "=== FlashInfer Installer for DGX Spark (GB10) ==="
echo ""

# Check venv exists
if [ ! -f "$PYTHON" ]; then
    echo "[ERROR] vLLM venv not found at $VENV"
    echo "        Run the vLLM setup first."
    exit 1
fi

# Check if already installed
if "$PYTHON" -c "import flashinfer; print(f'FlashInfer {flashinfer.__version__} already installed')" 2>/dev/null; then
    echo "[OK] FlashInfer is already installed."
    echo "     The smart launcher will auto-enable fp8 KV cache."
    exit 0
fi

# Detect CUDA and torch versions
CUDA_VER=$("$PYTHON" -c "import torch; print(torch.version.cuda)" 2>/dev/null || echo "unknown")
TORCH_VER=$("$PYTHON" -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")
PYTHON_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)

echo "Environment:"
echo "  Python:  $PYTHON_VER"
echo "  PyTorch: $TORCH_VER"
echo "  CUDA:    $CUDA_VER"
echo ""

# FlashInfer provides pre-built wheels for specific torch+cuda combos.
# For GB10 (aarch64 + CUDA 13.0), we may need to build from source.
# Try pre-built wheel first, fall back to source build.

export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export MAX_JOBS=2  # Prevent OOM during compilation on GB10

echo "Attempting to install FlashInfer..."
echo ""

# Strategy 1: Try official pre-built wheel (may not exist for aarch64+cu130)
echo "--- Strategy 1: Pre-built wheel ---"
if "$PIP" install flashinfer-python --quiet 2>/dev/null; then
    echo "[OK] FlashInfer installed via pre-built wheel."
elif "$PIP" install flashinfer --quiet 2>/dev/null; then
    echo "[OK] FlashInfer installed via pre-built wheel."
else
    echo "[INFO] No pre-built wheel available. Building from source..."
    echo ""

    # Strategy 2: Build from source
    echo "--- Strategy 2: Build from source ---"
    BUILD_DIR=$(mktemp -d)
    cd "$BUILD_DIR"

    git clone --depth 1 https://github.com/flashinfer-ai/flashinfer.git
    cd flashinfer

    echo "Building FlashInfer (this may take 10-20 minutes)..."
    echo "  MAX_JOBS=$MAX_JOBS (to prevent OOM)"
    echo "  CUDA_HOME=$CUDA_HOME"
    echo ""

    FLASHINFER_CUDA_ARCHS="12.1" \
    MAX_JOBS=$MAX_JOBS \
    "$PIP" install -e . --no-build-isolation 2>&1 | tail -20

    cd /
    rm -rf "$BUILD_DIR"
fi

# Verify installation
echo ""
if "$PYTHON" -c "import flashinfer; print(f'FlashInfer {flashinfer.__version__} installed successfully')" 2>/dev/null; then
    echo ""
    echo "============================================"
    echo "  FlashInfer installation complete!"
    echo ""
    echo "  Next steps:"
    echo "  1. Restart vLLM: bash manage_services.sh stop-vllm"
    echo "  2. Start vLLM:  bash smart_start_vllm.sh"
    echo "  3. fp8 KV cache will be auto-enabled"
    echo "============================================"
else
    echo "[ERROR] FlashInfer installation failed."
    echo "        Check the build output above for errors."
    echo "        Common issues:"
    echo "        - CUDA_HOME not set correctly (should be /usr/local/cuda)"
    echo "        - Missing ninja: pip install ninja"
    echo "        - OOM during build: set MAX_JOBS=1"
    exit 1
fi
