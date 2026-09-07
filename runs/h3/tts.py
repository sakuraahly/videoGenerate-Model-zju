"""book-14 T2b：中文语音合成（edge-tts；spark 已实测：pypi 可装、bing 端点可达、合成成功）。

职责：文本/SRT → 中文语音音轨（替换原音轨），供后处理链与 h3_submit 完成钩子使用。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"  # 女声/新闻小说；备选 zh-CN-YunxiNeural(男声)

# 八审：短名→全名映射层（原为 h3_submit main() 局部 _V_ALIASES，工具侧无法复用；
# 置于此公开常量，S6 tools 透传短名、S13/F5-TTS 音色扩展等处均可复用）
VOICE_ALIASES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "yunxi": "zh-CN-YunxiNeural",
    # 英文台词（父子英文对话/画外独白）：短名 aria=en-US-AriaNeural（美音女声；男英文用 en-US-ChristopherNeural 待登记）
    "aria": "en-US-AriaNeural",
    "en-aria": "en-US-AriaNeural",
}

_SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})")


def probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _edge_tts_cmd() -> list:
    """定位 edge-tts 可执行（当前解释器/PATH/qwen-agent-venv 三路探测）。"""
    import shutil
    import sys
    p = shutil.which("edge-tts")
    if p:
        return [p]
    exe = Path(sys.executable)
    cands = [str(exe.parent / "edge-tts"),
             str(exe.parent.parent / "bin" / "edge-tts"),
             "/home/Developer/qwen-agent-venv/bin/edge-tts"]
    for c in cands:
        if Path(c).is_file():
            return [c]
    raise ValueError("edge-tts 不可用（未安装或不在 PATH；请 pip install edge-tts 到运行解释器）")


def _sanitize_script(text: str) -> str:
    """book-18：台词脚本规范——无标点句尾不加；长度提示（不截断，仅告警用）。"""
    t = str(text or "").strip()
    if not t:
        return ""
    # 常见瑕疵：全角空格/多余空白
    t = " ".join(t.replace(chr(12288), " ").split())
    return t


def _voice_key(voice: str) -> str:
    """音色短名键（本地参考样本文件名）：全名→短名；未知→xiaoxiao。"""
    v = str(voice or "")
    for k, full in VOICE_ALIASES.items():
        if v == full:
            return k
    if v in VOICE_ALIASES:
        return v
    return "xiaoxiao"


# ---- S13 P 链①：本地 TTS（F5-TTS 魔搭权重 + vocos；替代 edge-tts 云链） ----
LOCAL_TTS_PY = os.environ.get(
    "LOCAL_TTS_PY", "/home/Developer/ai/tts-venv/bin/python3")
COSY_TTS_PY = os.environ.get(
    "COSY_TTS_PY", "/home/Developer/ai/cosy-venv/bin/python3")
_REF_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "tts_refs"
REF_SAMPLE_TEXT = "我们一起去公园散步吧，阳光很好。"
TTS_BACKENDS = ("edge", "local", "cosy")


def synth_local(text: str, out: Path, voice: str = DEFAULT_VOICE) -> float:
    """F5-TTS 本地合成（魔搭权重，克隆参考样本音色；CPU≈53s/句）。

    依赖 spark ~/ai/tts-venv + 模型缓存（F5TTS_v1_Base + vocos）与
    assets/tts_refs/<voice_key>.wav 参考样本；缺失抛 ValueError（edge-tts 过渡保留）。
    """
    text = str(text or "").strip()
    if not text:
        raise ValueError("TTS 文本为空")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not Path(LOCAL_TTS_PY).is_file():
        raise ValueError(f"本地 TTS 环境缺失: {LOCAL_TTS_PY}（spark: python3 -m venv ~/ai/tts-venv "
                         f"&& pip install f5-tts modelscope && 下载魔搭 AI-ModelScope/F5-TTS）")
    key = _voice_key(voice)
    ref_wav = _REF_DIR / f"{key}.wav"
    ref_txt = _REF_DIR / f"{key}.txt"
    if not ref_wav.is_file() or not ref_txt.is_file():
        raise ValueError(f"本地 TTS 参考样本缺失: {ref_wav}（edge-tts 生成后入库）")
    script = str(Path(__file__).resolve().parent / "tts_local_check.py")
    cmd = [LOCAL_TTS_PY, script, "--text", text, "--ref-file", str(ref_wav),
           "--ref-text", ref_txt.read_text(encoding="utf-8").strip(),
           "--output", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 200:
        raise ValueError("F5-TTS 合成失败: " + (r.stderr or "")[-400:])
    d = probe_duration(out)
    if d and d < 0.3:
        raise ValueError(f"TTS 音频过短({d:.2f}s)：{out.name}")
    return d


def synth_cosy(text: str, out: Path, voice: str = DEFAULT_VOICE) -> float:
    """CosyVoice2-0.5B 本地合成（自然音色；GPU 优先、OOM 自动转 CPU）。

    依赖 spark ~/ai/cosy-venv + 模型 ~/ai/CosyVoice2-0.5B（魔搭）；参考样本与 F5-TTS 同源
    （assets/tts_refs/<voice_key>）；环境/样本缺失抛 ValueError（回落 local/edge）。
    """
    text = str(text or "").strip()
    if not text:
        raise ValueError("TTS 文本为空")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not Path(COSY_TTS_PY).is_file():
        raise ValueError(f"CosyVoice2 环境缺失: {COSY_TTS_PY}（spark: python3 -m venv ~/ai/cosy-venv "
                         f"+ cosyvoice-src(源码) + 魔搭 iic/CosyVoice2-0.5B + 依赖链）")
    key = _voice_key(voice)
    ref_wav = _REF_DIR / f"{key}.wav"
    ref_txt = _REF_DIR / f"{key}.txt"
    if not ref_wav.is_file() or not ref_txt.is_file():
        raise ValueError(f"CosyVoice2 参考样本缺失: {ref_wav}")
    script = str(Path(__file__).resolve().parent / "tts_cosy_check.py")
    cmd = [COSY_TTS_PY, script, "--text", text, "--ref-file", str(ref_wav),
           "--ref-text", ref_txt.read_text(encoding="utf-8").strip(),
           "--output", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 200:
        raise ValueError("CosyVoice2 合成失败: " + (r.stderr or "")[-400:])
    d = probe_duration(out)
    if d and d < 0.3:
        raise ValueError(f"TTS 音频过短({d:.2f}s)：{out.name}")
    return d


def synthesize(text: str, out: Path, voice: str = DEFAULT_VOICE, rate: str = "-8%",
               backend: str = "cosy") -> float:
    """合成语音到 out（cosy=CosyVoice2 自然音色默认 / local=F5-TTS / edge=在线云）；返回时长秒。"""
    text = str(text or "").strip()
    if not text:
        raise ValueError("TTS 文本为空")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _b = str(backend or "cosy").lower()
    if _b == "local":
        return synth_local(text, out, voice=voice)
    if _b == "cosy":
        return synth_cosy(text, out, voice=voice)
    # book-18：--rate=-8% 用等号语法（argparse 会把以 - 开头的值当成旗标）
    cmd = _edge_tts_cmd() + ["--voice", voice, "--rate=" + rate, "--text", text, "--write-media", str(out)]
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
        # book-18：单句失败重试 1 次（逐句产出，不整段重来）
        try:
            d = synthesize(text, wav, voice=voice)
        except Exception as e:  # noqa: BLE001
            _log_note = None
            try:
                d = synthesize(text, wav, voice=voice)
            except Exception as e2:  # noqa: BLE001
                raise ValueError(f"第 {i} 句台词两次合成失败: {e2}") from e2
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


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def prepare_speech(text: str, voice: str = DEFAULT_VOICE, out_dir: Path = None,
                    backend: str = "edge") -> dict:
    """二轮审阅：解耦出 (speech, srt, dur)——供合并单次编码链（增强+字幕同 -vf）先行准备。"""
    out_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="tts_prep_"))
    speech = out_dir / "speech.mp3"
    spd = synthesize(text, speech, voice=voice, backend=backend)
    srt = out_dir / "speech.srt"
    srt.write_text(f"1\n00:00:00,000 --> {_srt_time(spd)}\n{text}\n", encoding="utf-8")
    return {"speech": speech, "srt": srt, "speech_dur": spd}


def replace_audio_only(input_video: Path, audio: Path, out: Path, dur: float = 0.0) -> Path:
    """二轮审阅：仅替换音轨（视频 copy，不重编码）——合并链最后一环。"""
    input_video = Path(input_video)
    out = Path(out)
    try:
        dur = float(dur or 0)
    except (TypeError, ValueError):
        dur = 0.0
    out = Path(out)
    tmp = out.with_name(out.stem + "_aud" + out.suffix)
    cmd = ["ffmpeg", "-y", "-i", str(input_video), "-i", str(audio),
           "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-filter:a", "apad,afftdn=nf=-25,loudnorm=I=-14:TP=-1.0:LRA=11", "-c:a", "aac", "-b:a", "192k"]
    if dur and dur > 0:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += [str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not tmp.is_file():
        raise ValueError("音轨替换(仅copy)失败: " + (r.stderr or "")[-300:])
    tmp.replace(out)
    return out


def attach_speech_and_subtitle(input_video: Path, text: str, out: Path = None,
                               voice: str = DEFAULT_VOICE, srt_path: Path = None,
                               fontsize: int = 0, backend: str = "edge") -> dict:
    """book-14 T2b v2#3：合成中文语音 → 整句 SRT(0→语音时长) → 烧录字幕 → 替换音轨(apad 保时长)。
    返回 {'path', 'speech_dur', 'srt', 'speech'}（speech=语音产物路径，供混音/ASR 复用）；
    全部失败即抛（不产半成品）。"""
    from h3.postprocess import render_subtitle
    input_video = Path(input_video)
    dest = Path(out) if out else input_video
    speech = Path(tempfile.mkstemp(suffix=".mp3")[1])
    with_sub = dest.with_name(dest.stem + "_sub" + dest.suffix)
    tmp_out = dest.with_name(dest.stem + "_v2" + dest.suffix)
    res = None
    try:
        dur = probe_duration(input_video)
        spd = synthesize(text, speech, voice=voice, backend=backend)
        srt = Path(srt_path) if srt_path else dest.with_name(dest.stem + ".srt")
        srt.write_text(f"1\n00:00:00,000 --> {_srt_time(spd)}\n{text}\n", encoding="utf-8")
        render_subtitle(input_video, with_sub, srt, fontsize=fontsize)
        cmd = ["ffmpeg", "-y", "-i", str(with_sub), "-i", str(speech),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-filter:a", "apad,afftdn=nf=-25,loudnorm=I=-14:TP=-1.0:LRA=11", "-c:a", "aac", "-b:a", "192k"]
        if dur and dur > 0:
            cmd += ["-t", f"{dur:.3f}"]
        cmd += [str(tmp_out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0 or not tmp_out.is_file():
            raise ValueError("TTS 音轨替换失败: " + (r.stderr or "")[-300:])
        tmp_out.replace(dest)
        with_sub.unlink(missing_ok=True)
        res = {"path": dest, "speech_dur": spd, "srt": srt, "speech": speech}
        return res
    finally:
        if res is None:  # 失败清理语音产物；成功交由调用方（混音/ASR 复用）
            speech.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)
        with_sub.unlink(missing_ok=True)


def replace_with_speech_text(input_video: Path, text: str, out: Path = None,
                             voice: str = DEFAULT_VOICE) -> Path:
    """整段文本 → 中文语音 → 替换视频音轨（语音 apad 至视频时长，保留完整画面；
    临时文件+原子替换；防 -shortest 截断、防原地写失败）。"""
    input_video = Path(input_video)
    dest = Path(out) if out else input_video
    tmp_out = dest.with_name(dest.stem + "_tts" + dest.suffix)
    speech = Path(tempfile.mkstemp(suffix=".mp3")[1])
    dur = probe_duration(input_video)
    try:
        synthesize(text, speech, voice=voice)
        cmd = ["ffmpeg", "-y", "-i", str(input_video), "-i", str(speech),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-filter:a", "apad", "-c:a", "aac", "-b:a", "192k"]
        if dur and dur > 0:
            cmd += ["-t", f"{dur:.3f}"]
        cmd += [str(tmp_out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0 or not tmp_out.is_file():
            raise ValueError("TTS 音轨替换失败: " + (r.stderr or "")[-300:])
        tmp_out.replace(dest)
    finally:
        speech.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)
    return dest


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