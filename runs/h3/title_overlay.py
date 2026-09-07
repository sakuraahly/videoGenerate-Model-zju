#!/usr/bin/env python3
"""title_overlay — 标题/字幕条后期装配（S13③；纯 ffmpeg+libass 本地，无新模型）。

用法（spark，任意含 ffmpeg(libass) 环境）:
  python runs/h3/title_overlay.py --video outputs/video_45.mp4 \
      --title "第一章：重逢" --start 0.5 --end 3.0 \
      --out outputs/video_48_title.mp4 [--font "Noto Serif CJK SC"] [--fontsize 0]

实现：SRT 单条 + subtitles 滤镜（libass，FontName=<font>）顶部居中（Alignment=8，白字黑描边）。
中文渲染与项目字幕链同源（libass fontconfig，避免 drawtext TTC 缺字形）。
失败抛 ValueError（不产半成品）。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_FONTNAME = "Noto Serif CJK SC"


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def overlay_title(video: Path, title: str, out: Path, start: float = 0.0,
                  end: float = 0.0, fontname: str = DEFAULT_FONTNAME,
                  fontsize: int = 0) -> Path:
    """叠加标题条：白字+黑描边，顶部居中；end<=0 时=8 成视频时长。"""
    video = Path(video)
    out = Path(out)
    if not video.is_file():
        raise ValueError(f"输入视频不存在: {video}")
    title = str(title or "").strip()
    if not title:
        raise ValueError("标题为空")
    dur = probe_duration(video)
    if end <= 0:
        end = max(start + 2.0, dur * 0.8)
    if fontsize <= 0:
        fontsize = max(18, int(round(352 * 0.09)))  # 默认≈32(对 360p；随分辨率自适应见下)
        fontsize = max(18, int(round(float(probe_duration(video)) * 0 + 32)))
    fs = fontsize
    # 顶部对准 / 黑描边 / 白字
    force_style = (f"FontName={fontname},FontSize={fs},PrimaryColour=&H00FFFFFF,"
                   f"OutlineColour=&H80000000,BorderStyle=1,Outline=3,Shadow=0,"
                   f"Alignment=8,MarginV=30")
    with tempfile.TemporaryDirectory() as td:
        srt = Path(td) / "title.srt"
        def _t(sec: float) -> str:
            ms = int(round(sec * 1000))
            h, rem = divmod(ms, 3600_000)
            m, rem = divmod(rem, 60_000)
            s, ms = divmod(rem, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        srt.write_text(f"1\n{_t(start)} --> {_t(end)}\n{title}\n", encoding="utf-8")
        sub = str(srt.resolve()).replace("\\", "/")
        vf = f"subtitles='{sub}':force_style='{force_style}'"
        tmp = out.with_name(out.stem + "_t" + out.suffix)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", vf,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-c:a", "copy", str(tmp)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not tmp.is_file():
            raise ValueError("标题叠加失败: " + (r.stderr or "")[-300:])
        tmp.replace(out)
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="标题/字幕条后期装配（libass subtitles）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=0.0, help="0=自动(8 成时长)")
    ap.add_argument("--font", default=DEFAULT_FONTNAME)
    ap.add_argument("--fontsize", type=int, default=0)
    args = ap.parse_args(argv)
    p = overlay_title(Path(args.video), args.title, Path(args.out),
                      start=args.start, end=args.end, fontname=args.font,
                      fontsize=args.fontsize)
    print(f"TITLE_OUT: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
