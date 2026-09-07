#!/usr/bin/env python3
"""asr_check — 视频/音频语音可辨析客观验收（书-19 §13 P 链④；魔搭 iic/SenseVoiceSmall-onnx）。

FunASR SenseVoiceSmall (ONNX) 推理：给出 ASR 文本作可辨析初判（语义通畅=可辨析；
乱语/空文本=不可辨析——如实标注，不替代人工）。

用法（spark 上，asr-venv 激活）:
  python runs/h3/asr_check.py <video|audio path> [--lang zh|en|auto]
模型路径自动探测：~/.cache/modelscope/models/iic--SenseVoiceSmall-onnx/snapshots/master
（缺 bpe.model 时自动从 iic--SenseVoiceSmall 复制）；输出 ASR 文本+判读行。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_HOME = Path.home()


def _onnx_dir() -> Path:
    snap = _HOME / ".cache/modelscope/models/iic--SenseVoiceSmall-onnx/snapshots/master"
    if not (snap / "model_quant.onnx").exists():
        raise FileNotFoundError(f"模型未下载: 先运行 python -c "
                                f"\"from funasr_onnx import SenseVoiceSmall; SenseVoiceSmall(model_dir='iic/SenseVoiceSmall-onnx')\"")
    bpe = snap / "chn_jpn_yue_eng_ko_spectok.bpe.model"
    if not bpe.exists():
        src = (_HOME / ".cache/modelscope/models/iic--SenseVoiceSmall/snapshots/master"
               / "chn_jpn_yue_eng_ko_spectok.bpe.model")
        if src.exists():
            import shutil
            shutil.copy2(src, bpe)
    return snap


def extract_wav(path: str, tmp: Path) -> Path:
    """提取 16k 单声道 wav；已经是 wav 直接返回。"""
    p = Path(path)
    if p.suffix.lower() == ".wav":
        return p
    wav = tmp / "asr.wav"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p),
                        "-ar", "16000", "-ac", "1", str(wav)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 提取失败: {r.stderr[:200]}")
    return wav


def run_asr(wav: Path) -> str:
    from funasr_onnx import SenseVoiceSmall

    m = SenseVoiceSmall(model_dir=str(_onnx_dir()), batch_size=1, quantize=True)
    res = m(str(wav))
    # funasr_onnx 0.4.2 实际返回 list[str]（官方 README 形态）；兼容 list[dict]
    item = res[0] if isinstance(res, list) and res else res
    if isinstance(item, dict):
        return str(item.get("text", ""))
    return str(item or "")


def text_similarity(a: str, b: str) -> float:
    """ASR 文本与目标文本的字符级相似度（剥 SenseVoice 标签/标点；中文按字英文按字母）。"""
    import difflib
    import re as _re
    def _norm(s):
        s = _re.sub(r"<\|[^|>]*\|>", "", str(s or ""))
        s = _re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s).lower()
        return s
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def verdict(text: str) -> str:
    """粗判：非空+含足够中文/英文单词=可能可辨析；乱语（低词数/异常）如实标注。"""
    t = text.strip()
    if not t:
        return "no-speech"
    # 中文按字符数判（ASR 文本为连续汉字）；英文按词数
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    words = [w for w in t.split() if len(w) > 1]
    if cjk < 3 and len(words) < 3:
        return "dubious(too short)"
    # 简单语义通畅性无法自动判定 → 交人工；给出文本
    return "has-speech (human review)" 


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="ASR 可辨析验收（SenseVoiceSmall ONNX）")
    ap.add_argument("media", help="视频/音频路径")
    ap.add_argument("--compare", default="", help="可选：目标文本（ASR 相似度验收，如 tts_text 台词）")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as td:
        wav = extract_wav(args.media, Path(td))
        text = run_asr(wav)
    print(f"ASR_TEXT: {text}")
    print(f"VERDICT: {verdict(text)}")
    if args.compare:
        score = text_similarity(text, args.compare)
        print(f"ASR_SCORE: {score:.3f}")
        print(f"ASR_MATCH: {'ok' if score >= 0.6 else 'poor'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
