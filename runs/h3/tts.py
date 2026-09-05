"""book-14 T2b：中文语音合成（edge-tts；spark 已实测：pypi 可装、bing 端点可达、合成成功）。

职责：文本/SRT → 中文语音音轨（替换原音轨），供后处理链与 h3_submit 完成钩子使用。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"  # 女声/新闻小说；备选 zh-CN-YunxiNeural(男声)

_SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})")


def probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def synthesize(text: str, out: Path, voice: str = DEFAULT_VOICE, rate: str = "+0%") -> float:
    """edge-tts 合成中文语音到 out（mp3/wav）；返回时长秒；失败抛 ValueError。"""
    text = str(text or "").strip()
    if not text:
        raise ValueError("TTS 文本为空")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["edge-tts", "--voice", voice, "--rate", rate, "--text", text, "--write-media", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 200:
        raise ValueError("TTS 合成失败: " + (r.stderr or "")[-300:])
    d = probe_duration(out)
    if d and d < 0.3:
        raise ValueError(f"TTS 音频过短({d:.2f}s)：{out.name}")
    return d


def parse_srt(srt: Path) -> list:
    """解析 SRT → [(start_s, end_s, text)]；无有效块抛 ValueError。"""
    srt = Path(srt)
    if not srt.is_file():
        raise ValueError(f"字幕文件不存在: {srt}")
    raw = srt.read_text(encoding="utf-8-sig", errors="replace")
    out: list = []
    for block in raw.strip().split("\n\n"):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        tl = next((l for l in lines if "-->" in l), "")
        if not tl:
            continue
        m1 = _SRT_TIME.search(tl)
        m2 = _SRT_TIME.search(tl.split("-->")[1] if "-->" in tl else "")
        if not m1 or not m2:
            continue
        def _sec(m):
            h, mi, s, ms = (int(g) for g in m.groups())
            return h * 3600 + mi * 60 + s + ms / 1000.0
        idx = lines.index(tl)
        text = " ".join(lines[idx + 1:]) if idx + 1 < len(lines) else ""
        if text:
            out.append((_sec(m1), _sec(m2), text))
    if not out:
        raise ValueError("SRT 无有效具时间轴字幕块")
    return out


def build_srt_speech(srt: Path, out: Path, voice: str = DEFAULT_VOICE, tmpdir: Path = None) -> float:
    """逐句合成字幕语音：每句按 SRT 起点对齐，句间静音填充；返回最终音轨时长。"""
    segs = parse_srt(srt)
    tmp = Path(tmpdir) if tmpdir else Path(tempfile.mkdtemp(prefix="tts_"))
    parts = []
    prev_end = 0.0
    for i, (start, end, text) in enumerate(sorted(segs), 1):
        wav = tmp / f"line_{i:03d}.mp3"
        try:
            d = synthesize(text, wav, voice=voice)
        except Exception as e:
            raise ValueError(f"第 {i} 句台词合成失败: {e}") from e
        parts.append((max(start, prev_end), d, wav))
        prev_end = max(start, prev_end) + d
    total = max((p[0] + p[1] for p in parts), default=0.0)
    build_track(parts, total, out, tmp)
    return total


def build_track(parts: list, total: float, out: Path, tmp: Path) -> Path:
    """把 [(abs_start, dur, wav)] 按起点对齐为一条音轨（静音填空）；输出 WAV 44.1k 单声道。"""
    out = Path(out)
    parts = sorted(parts)
    if not parts:
        raise ValueError("无语音片段，无法建音轨")
    cmd = ["ffmpeg", "-y"]
    for (_s, _d, wav) in parts:
        cmd += ["-i", str(wav)]
    filters, labels = [], []
    for i, (start, _dur, _wav) in enumerate(parts):
        ms = int(round(start * 1000))
        filters.append(f"[{i}:a]adelay={ms}|{ms}[d{i}]")
        labels.append(f"[d{i}]")
    end = max((s + d for s, d, _w in parts), default=0.0)
    filters.append("".join(labels)
                   + f"amix=inputs={len(parts)}:normalize=0,apad,tpad=stop_mode=clone:stop_duration={end:.3f},atrim=0:{end:.3f}[aout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[aout]",
            "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not out.is_file():
        raise ValueError("音轨合成失败: " + (r.stderr or "")[-300:])
    return out


def replace_with_speech_text(input_video: Path, text: str, out: Path = None,
                             voice: str = DEFAULT_VOICE) -> Path:
    """整段文本 → 中文语音 → 替换视频音轨（-shortest；保留画面）。返回产物路径。"""
    from h3.postprocess import mix_audio
    input_video = Path(input_video)
    out = Path(out) if out else input_video
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    speech = Path(tmp.name)
    tmp.close()
    try:
        synthesize(text, speech, voice=voice)
        mix_audio(input_video, out, speech)
    finally:
        speech.unlink(missing_ok=True)
    return out


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="book-14 T2b 中文语音合成")
    ap.add_argument("cmd", choices=["test", "replace"])
    ap.add_argument("--text", default="", help="待合成文本")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--video", default="", help="replace: 输入视频")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    if a.cmd == "test":
        d = synthesize(a.text or "你好，这是中文语音测试。", Path(a.out or "/tmp/tts_test.mp3"), voice=a.voice)
        print(f"TTS_OK duration={d:.2f}s out={a.out}")
    elif a.cmd == "replace":
        out = replace_with_speech_text(Path(a.video), a.text, voice=a.voice)
        print(f"TTS_REPLACE_OK out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())