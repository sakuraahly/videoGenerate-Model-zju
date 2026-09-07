#!/usr/bin/env python3
"""tts_cosy_check — CosyVoice2 本地合成（S13 P链①b；魔搭 iic/CosyVoice2-0.5B）。

更自然的音色后端（2026-09-07 用户定案：中文女声/英文均走本地模型生成的自然音色）。
GPU 优先；CUDA 内存不足时自动 CUDA_VISIBLE_DEVICES="" 转 CPU（GB10 队列忙时常见，登记）。

用法（spark，cosy-venv）:
  ~/ai/cosy-venv/bin/python3 runs/h3/tts_cosy_check.py \
      --text "欢迎使用本地语音合成系统。" \
      --ref-file assets/tts_refs/xiaoxiao.wav --ref-text "<样本对应文本>" \
      --output /tmp/cosy_out.wav
输出: OUT_WAV <path> 与用时（CPU ≈47s/句；GPU≈秒级）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_HOME = Path.home()
_COSY = _HOME / "ai/CosyVoice2-0.5B"
_SRC = _HOME / "ai/cosyvoice-src"


def _resolve() -> Path:
    if not (_COSY / "cosyvoice2.yaml").is_file():
        raise FileNotFoundError(
            f"CosyVoice2 模型未下载: {_COSY}（先执行: "
            f"from modelscope import snapshot_download; "
            f"snapshot_download('iic/CosyVoice2-0.5B', local_dir='~/ai/CosyVoice2-0.5B')")
    if not _SRC.exists():
        raise FileNotFoundError(f"CosyVoice2 代码缺失: {_SRC}（git clone 通道被墙，用 codeload zip 落地）")
    return _COSY


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="CosyVoice2 本地合成（自然音色后端）")
    ap.add_argument("--text", required=True, help="合成文本")
    ap.add_argument("--ref-file", required=True, help="参考音频（音色克隆样本）")
    ap.add_argument("--ref-text", required=True, help="参考音频对应文本")
    ap.add_argument("--output", default="", help="输出 wav 路径（默认当前目录 cosy_out.wav）")
    args = ap.parse_args(argv)

    model_dir = _resolve()
    if not Path(args.ref_file).is_file():
        raise ValueError(f"参考样本缺失: {args.ref_file}")
    sys.path.insert(0, str(_SRC))
    from cosyvoice.cli.cosyvoice import CosyVoice2  # noqa: E402
    import torchaudio  # noqa: E402

    out = args.output or "cosy_out.wav"

    def run(cpu: bool) -> float:
        if cpu:
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        t0 = time.time()
        cv = CosyVoice2(str(model_dir), load_jit=False, load_trt=False, fp16=False)
        for _i, j in enumerate(cv.inference_zero_shot(
                args.text, args.ref_text, args.ref_file)):
            torchaudio.save(out, j["tts_speech"], cv.sample_rate)
        return time.time() - t0

    try:
        dt = run(cpu=False)  # GPU 优先
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "out of memory" in msg.lower() or "CUDA error" in msg.lower():
            print("GPU_OOM: fallback to CPU", flush=True)
            dt = run(cpu=True)
        else:
            raise
    size = os.path.getsize(out)
    print(f"OUT_WAV: {out} ({size} bytes, {dt:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
