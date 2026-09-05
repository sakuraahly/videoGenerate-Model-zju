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
            sharpen: float = 0.4, color: str = "", interp: bool = False) -> dict:
    """执行后处理并断言输出参数。返回 probe(out)。失败抛 ValueError（确定性）。"""
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
    if not vf:
        raise ValueError("没有可执行的处理项（scale/denoise/sharpen/color/interp 至少一项）")
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
    a = ap.parse_args(argv)
    try:
        if a.cmd == "probe":
            print(json.dumps(probe(a.input), ensure_ascii=False))
            return 0
        inp = Path(a.input)
        out = Path(a.out) if a.out else inp.with_name(inp.stem + "_pp" + inp.suffix)
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
