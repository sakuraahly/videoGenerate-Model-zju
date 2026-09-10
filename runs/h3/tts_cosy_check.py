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
    ap.add_argument("--speed", type=float, default=0.95,
                    help="语速（CosyVoice2 speed；0.95 略放缓更自然；1.0 偏快平有机械味）")
    ap.add_argument("--force-cpu", action="store_true",
                    help="强制 CPU 合成（避开 ComfyUI/SGLang 的 GPU 占用；OOM 自动子进程回退）")
    ap.add_argument("--instruct", default="",
                    help="指令语气（CosyVoice2 inference_instruct2；如'用沉稳不紧不慢的语气说'——"
                         "人物个性由语气指令表达；缺省=零样本自然语气）")
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
        # 零样本口径：spk2info 先注册参考样本（frontend 以 wav 路径为 spk_id 索引；
        # 未注册会 KeyError——见 2026-09-09 新音色样本踩坑）。注册后 zero-shot 分支走缓存。
        key = str(args.ref_file)
        if key not in cv.list_available_spks():
            cv.add_zero_shot_spk(args.ref_text, args.ref_file, key)
        if args.instruct:
            if not hasattr(cv, "inference_instruct2"):
                raise ValueError("模型无 inference_instruct2（需要 CosyVoice2 指令模型形态）")
            gen = cv.inference_instruct2(args.text, args.instruct, args.ref_text,
                                         args.ref_file, speed=args.speed)
        else:
            gen = cv.inference_zero_shot(args.text, args.ref_text, args.ref_file,
                                         speed=args.speed)
        for _i, j in enumerate(gen):
            torchaudio.save(out, j["tts_speech"], cv.sample_rate)
        return time.time() - t0

    try:
        dt = run(cpu=args.force_cpu)  # GPU 优先（--force-cpu 直接 CPU）
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "out of memory" in msg.lower() or "CUDA error" in msg.lower() or "AcceleratorError" in msg:
            # GPU OOM：子进程 + 全新 CUDA_VISIBLE_DEVICES=''（当前进程的 CUDA 上下文无法变更）
            print("GPU_OOM: fallback to CPU child process", flush=True)
            import os as _os
            import subprocess as _sp
            env = dict(_os.environ)
            env["CUDA_VISIBLE_DEVICES"] = ""
            argv = [_os.path.abspath(__file__), "--force-cpu"]
            argv += sys.argv[1:]
            p = _sp.run([sys.executable] + argv, env=env, text=True, timeout=3600)
            if p.returncode != 0 or not Path(out).is_file():
                raise
            print("FALLBACK_CPU_OK", flush=True)
            return 0
        raise
    size = os.path.getsize(out)
    print(f"OUT_WAV: {out} ({size} bytes, {dt:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
