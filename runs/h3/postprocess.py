#!/usr/bin/env python3
"""postprocess — 视频交付质量增强链（book-14 T2，v1：ffmpeg 管线）。

能力（v1，全部用 ffmpeg，零额外模型依赖）：
  - 超分/放大：lanczos 缩放（--scale 2x 默认落地 720p→1440p 档）
  - 降噪：hqdn3d（去低步/压缩噪点——与 T1 4 步瑕疵补偿联动）
  - 锐化：unsharp（细节恢复）
  - 调色：--color ffmpeg 滤镜串（如 eq=contrast=1.05:saturation=1.1）
  - 插帧：--interp（minterpolate，默认关闭——慢/有伪影风险，Q 质量档）

红线与断言（book-14 升级纪律）：
  - 任何失败以非 0 退出 + 可读消息（不静默、不产出坏文件）；
  - 完成后用 ffprobe 断言：输出分辨率/时长符合预期（宽>=输入、时长偏差 <1.2s）；
  - 不改输入文件；输出写 --out（默认同目录 <stem>_pp.mp4）。

CLI：
  python runs/h3/postprocess.py <input> [--scale 2.0] [--denoise 1.0] [--sharpen 0.4]
      [--color "eq=..."] [--interp] [--out path]
  python runs/h3/postprocess.py probe <input>     # 只打印 ffprobe 参数（诊断）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def probe_av(path: str) -> dict:
    """五审新增（S10 用）：视频 + 音频流信息（probe() 只取 -select_streams v:0，音频结构性缺失）。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "stream=codec_type,codec_name,channels,width,height,r_frame_rate,nb_frames,duration",
         "-show_entries", "format=duration,size",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise ValueError("ffprobe(av) 失败: " + (r.stderr or r.stdout or "")[-200:])
    import json as _j
    d = _j.loads(r.stdout or "{}")
    _streams = d.get("streams") or []
    _v = next((s for s in _streams if s.get("codec_type") == "video"), {})
    _a = next((s for s in _streams if s.get("codec_type") == "audio"), {})
    v, a = _v, _a
    fmt = d.get("format") or {}
    return {"width": v.get("width"), "height": v.get("height"),
            "fps": v.get("r_frame_rate"), "frames": v.get("nb_frames"),
            "video_duration": v.get("duration", fmt.get("duration")),
            "audio_codec": a.get("codec_name"), "audio_channels": a.get("channels"),
            "audio_duration": a.get("duration"),
            "duration": fmt.get("duration"), "size": fmt.get("size")}


def probe(path: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError("ffprobe 失败: " + (r.stderr or r.stdout)[:200])
    d = json.loads(r.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    return {"width": int(st.get("width") or 0), "height": int(st.get("height") or 0),
            "fps": st.get("r_frame_rate", ""), "frames": int(st.get("nb_frames") or 0),
            "duration": float(st.get("duration") or 0)}


def process(input_path: Path, out: Path, scale: float = 2.0, denoise: float = 1.0,
            sharpen: float = 0.4, color: str = "", interp: bool = False,
            srt: Path = None, fontsize: int = 0, style_name: str = "Noto Sans CJK SC") -> dict:
    """执行后处理并断言输出参数。返回 probe(out)。失败抛 ValueError（确定性）。
    book-13 S2（二轮审阅）：srt 参数把字幕烧录并入**同一 -vf**（单次编码=增强+字幕，
    消除 process+render_subtitle 双次 CRF18 的代际损失）。"""
    input_path = Path(input_path)
    out = Path(out)
    if not input_path.is_file():
        raise ValueError(f"输入不存在: {input_path}")
    vf = []
    if scale and scale > 1.0:
        vf.append("scale=iw*%.2f:ih*%.2f:flags=lanczos" % (scale, scale))
    if denoise and denoise > 0:
        vf.append("hqdn3d=%.2f" % denoise)
    if sharpen and sharpen > 0:
        vf.append("unsharp=5:5:%.2f:5:5:0" % sharpen)
    if color:
        vf.append(color)
    if interp:
        vf.append("minterpolate=fps=48:mi_mode=mci:mc_mode=aobmc")
    if srt is not None:
        _fs = _subtitle_style(Path(srt), Path(input_path), fontsize, style_name)
        vf.append(_fs[0])
    if not vf:
        raise ValueError("没有可执行的处理项（scale/denoise/sharpen/color/interp/srt 至少一项）")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vf", ",".join(vf),
           "-c:v", "libx264", "-preset", "fast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise ValueError("ffmpeg 失败: " + (r.stderr or "")[-300:])
    info = probe(str(out))
    pin = probe(str(input_path))
    if scale > 1 and info["width"] < int(pin["width"] * scale * 0.9):
        raise ValueError(f"输出分辨率异常: {info['width']}x{info['height']}")
    if abs(info["duration"] - pin["duration"]) > 1.2:
        raise ValueError(f"时长漂移: {info['duration']:.2f}s vs {pin['duration']:.2f}s")
    return info


CJK_FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]


def check_cjk_font() -> str:
    """返回可用 CJK 字体（book-14 T2b：中文字幕不乱码的前提；缺失即确定性报错）。"""
    for c in CJK_FONTS:
        if os.path.isfile(c):
            return c
    raise ValueError("未找到 CJK 字体（请安装 fonts-noto-cjk）")


def validate_srt(srt: Path) -> int:
    """SRT 基本校验：返回字幕块数；无效抛 ValueError（不静默烧入空字幕）。"""
    if not srt.is_file():
        raise ValueError(f"字幕文件不存在: {srt}")
    text = srt.read_text(encoding="utf-8-sig", errors="replace")
    blocks = [b for b in text.strip().split("\n\n") if "-->" in b]
    if not blocks:
        raise ValueError("SRT 无有效字幕块（需含 --> 时间轴）")
    return len(blocks)


def _subtitle_style(srt: Path, src: Path, fontsize: int = 0,
                     style_name: str = "Noto Sans CJK SC") -> tuple:
    """字幕 vf 片段与字号计算：fontsize<=0 → 随分辨率等比（0.07×H；二轮审阅：默认绝对 20px 已废）。"""
    check_cjk_font()
    validate_srt(Path(srt))
    if fontsize <= 0:
        info0 = probe(str(src))
        fontsize = max(16, int(round(info0.get('height', 352)) * 0.07))
    margin_v = max(16, int(round(float(probe(str(src)).get('height', 352)) * 0.08)))
    force_style = f"FontName={style_name},FontSize={fontsize}," \
                  f"PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000," \
                  f"BorderStyle=1,Outline=2,Shadow=0,MarginV={margin_v}"
    sub_path = str(Path(srt).resolve()).replace("\\", "/").replace("`", "")
    return (f"subtitles='{sub_path}':force_style='{force_style}'", fontsize)


def render_subtitle(input_path: Path, out: Path, srt: Path, fontsize: int = 0,
                    style_name: str = "Noto Sans CJK SC") -> dict:
    """用 libass 烧录 SRT 到视频（中文字体；失败抛 ValueError）。
    ️二轮审阅：默认 fontsize=0 → 随分辨率等比（旧默认绝对 20px 会随 2x 增强静默变小）。"""
    _vf, _ = _subtitle_style(srt, input_path, fontsize, style_name)
    vf = _vf
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vf", vf,
           "-c:v", "libx264", "-preset", "fast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise ValueError("字幕烧录失败: " + (r.stderr or "")[-300:])
    info = probe(str(out))
    pin = probe(str(input_path))
    if info["width"] != pin["width"]:
        raise ValueError(f"字幕烧录改变分辨率: {pin['width']} -> {info['width']}")
    return info


def mix_tracks(input_video, out, main, bed=None,
                main_db=0.0, bed_db=-12.0):
    """三审修订：双轨混音——main 主轨（TTS 旁白）、bed 底轨（默认 -12dB）。
    volume 必须带 dB 后缀（裸数字=线性倍率：0.0=静音、-12.0=反转+放大削波——实测证实）；
    amix 加 normalize=0 保住 dB 相对配比（后续 loudnorm 统一整体响度）。失败抛 ValueError。"""
    if not Path(main).is_file():
        raise ValueError("主音轨不存在: " + str(main))
    if bed is not None and not Path(bed).is_file():
        raise ValueError("底轨音频不存在: " + str(bed))
    dur = _dur_or(probe(str(input_video)))
    inputs = ["-i", str(input_video), "-i", str(main)]
    if bed is not None:
        inputs += ["-i", str(bed)]
        filters = (f"[1:a]volume={main_db}dB[m0];[2:a]volume={bed_db}dB[m1];"
                   f"[m0][m1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
                   f"loudnorm=I=-14:TP=-1.0:LRA=11[outa]")
    else:
        filters = f"[1:a]volume={main_db}dB,apad,loudnorm=I=-14:TP=-1.0:LRA=11[outa]"
    cmd = ["ffmpeg", "-y"] + inputs + ["-map", "0:v", "-map", "[outa]", "-c:v", "copy",
           "-filter_complex", filters, "-c:a", "aac", "-b:a", "192k",
           "-t", dur, str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not Path(out).is_file():
        raise ValueError("双轨混音失败: " + (r.stderr or "")[-300:])
    return probe(str(out))


def _dur_or(info):
    """三审修订：duration 缺失直接抛错（0.0 会造成零长产物静默成功）。"""
    d = info.get("duration")
    if not d:
        raise ValueError("probe 未返回 duration（疑似输入损坏）")
    return str(float(d))

def mix_audio(input_path: Path, out: Path, audio: Path) -> dict:
    """单轨替换（非混流！二轮审阅更正 docstring）：以指定音频**替换**音轨（-shortest；失败抛 ValueError）。
    双轨混音用 mix_tracks()。"""
    if not audio.is_file():
        raise ValueError(f"音频不存在: {audio}")
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-i", str(audio),
           "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise ValueError("音频替换失败: " + (r.stderr or "")[-300:])
    info = probe(str(out))
    return info


def run_full(input_path: Path, out: Path, srt: Path = None, audio: Path = None,
             scale: float = 2.0, denoise: float = 1.0, sharpen: float = 0.4,
             bed_audio: Path = None) -> Path:
    """T2b 完整链（二轮/三轮审阅修订）：**单次编码**（增强+字幕并入同一 -vf）→ 音轨。
    audio=单轨替换（mix_audio）；audio+bed_audio=双轨混音（mix_tracks：主轨+底轨-12dB）。
    mix_tracks 由此接线（非死代码）。"""
    mid = out.with_name(out.stem + "_enh" + out.suffix)
    process(input_path, mid, scale=scale, denoise=denoise, sharpen=sharpen, srt=srt)
    if bed_audio is not None:
        mix_tracks(mid, out, audio or bed_audio, bed=bed_audio)
        mid.unlink(missing_ok=True)
    elif audio:
        mix_audio(mid, out, audio)
        mid.unlink(missing_ok=True)
    else:
        mid.replace(out) if mid.exists() else None
    return out


def run_fast(input_path: Path, out: Path) -> Path:
    """--postprocess fast 档（h3_submit 接入）：2x + 降噪 + 锐化。"""
    process(input_path, out, scale=2.0, denoise=1.0, sharpen=0.4)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="book-14 T2 质量增强链（ffmpeg）")
    ap.add_argument("cmd", choices=["process", "probe"])
    ap.add_argument("input", help="输入视频路径")
    ap.add_argument("--out", default="", help="输出路径（默认 <stem>_pp.mp4）")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--denoise", type=float, default=1.0)
    ap.add_argument("--sharpen", type=float, default=0.4)
    ap.add_argument("--color", default="")
    ap.add_argument("--interp", action="store_true")
    ap.add_argument("--subtitle", default="", help="SRT 字幕路径（中文字幕用 libass+Noto CJK）")
    ap.add_argument("--audio", default="", help="音轨文件（WAV/MP3 等）")
    ap.add_argument("--font-size", type=int, default=20)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "probe":
            print(json.dumps(probe(a.input), ensure_ascii=False))
            return 0
        inp = Path(a.input)
        out = Path(a.out) if a.out else inp.with_name(inp.stem + "_pp" + inp.suffix)
        if a.subtitle or a.audio:
            info = None
            run_full(inp, out, srt=Path(a.subtitle) if a.subtitle else None,
                     audio=Path(a.audio) if a.audio else None,
                     scale=a.scale, denoise=a.denoise, sharpen=a.sharpen)
            info = probe(str(out))
        else:
            info = process(inp, out, scale=a.scale, denoise=a.denoise,
                           sharpen=a.sharpen, color=a.color, interp=a.interp)
        print(f"POSTPROCESS_OUT: {out} w={info['width']} h={info['height']} "
              f"dur={info['duration']:.2f}s frames={info['frames']}", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 后处理失败: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
