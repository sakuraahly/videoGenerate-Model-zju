#!/usr/bin/env python3
"""tts_local_check — 本地 TTS 冒烟/验收（书-19 §13 P 链①；魔搭 AI-ModelScope/F5-TTS）。

F5-TTS (SWivid v1, vocos vocoder) 低要求模型——zero-shot 克隆参考音色合成中文。
模型/权重路径自动探测（spark 已缓存：魔搭 F5TTS_v1_Base(safetensors 1.35G) +
vocos(vocos-mel-24khz 54M, 经 hf-mirror 下载)；新环境请先下载）。

用法（spark，~/ai/tts-venv 激活）:
  python runs/h3/tts_local_check.py \
      --text "欢迎使用本地语音合成系统。" \
      --ref-file /tmp/f5_ref.wav --ref-text "我们一起去公园散步吧，阳光很好。" \
      --output /tmp/out.wav
输出: OUT_WAV <path> 与生成用时。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_HOME = Path.home()
_COMFY = _HOME / "ai/ComfyUI/models"
_CACHE = _HOME / ".cache/modelscope/models/AI-ModelScope--F5-TTS/snapshots/master"
_VOCOS = _HOME / "ai/vocos-mel-24khz"


def _comfy_paths():
    """ComfyUI models 目录（2026-09-07 用户指示：模型统一放 ComfyUI models 下；回落旧缓存）。"""
    ckpt = _COMFY / "f5-tts/F5TTS_v1_Base/model_1250000.safetensors"
    vocos = _COMFY / "f5-tts/vocos"
    if ckpt.exists() and (vocos / "pytorch_model.bin").exists():
        return ckpt, vocos
    return _CACHE / "F5TTS_v1_Base/model_1250000.safetensors", _VOCOS


def _resolve():
    ckpt, vocos = _comfy_paths()
    if not ckpt.exists():
        raise FileNotFoundError(f"模型未下载: {ckpt}（先 python -c \"from modelscope import snapshot_download; "
                                f"snapshot_download('AI-ModelScope/F5-TTS', allow_patterns=['F5TTS_v1_Base/*'])\"）")
    vocos = vocos / "pytorch_model.bin"
    if not vocos.exists():
        raise FileNotFoundError(f"vocos 权重未下载: {vocos}（HF_ENDPOINT=https://hf-mirror.com 下载 "
                                f"charactr/vocos-mel-24khz）")
    return ckpt, _VOCOS


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="本地 TTS 冒烟/验收（F5-TTS v1 + vocos）")
    ap.add_argument("--text", required=True, help="合成文本（中文）")
    ap.add_argument("--ref-file", required=True, help="参考音频（音色克隆样本）")
    ap.add_argument("--ref-text", required=True, help="参考音频对应文本")
    ap.add_argument("--output", default="", help="输出 wav 路径（默认当前目录 tts_out.wav）")
    ap.add_argument("--device", default="cpu", help="cpu/cuda")
    args = ap.parse_args(argv)

    ckpt, vocos = _resolve()
    from f5_tts.api import F5TTS

    t0 = time.time()
    tts = F5TTS(model="F5TTS_v1_Base", ckpt_file=str(ckpt),
                vocoder_local_path=str(vocos), device=args.device)
    out = args.output or "tts_out.wav"
    tts.infer(ref_file=args.ref_file, ref_text=args.ref_text,
              gen_text=args.text, file_wave=out)
    size = os.path.getsize(out)
    print(f"OUT_WAV: {out} ({size} bytes, {time.time()-t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
