#!/usr/bin/env python3
"""sfx_mix — 音效链完整版：音乐底轨 + 分段音效事件 + 原音轨 三路混音（S13/§11②③）。

背景（book-19 §11 用户反馈）：模型原生配乐不自然/脚步声不匹配 → 独立音效轨后期合成：
  原音轨(主,0dB) + 音乐底轨(默认 -12dB) + 音效事件(指定时间点播放,默认 -6dB)。
使用 amix normalize=0 保相对配比 + loudnorm 整体归一；失败抛 ValueError。

用法（spark，任意含 ffmpeg 环境）:
  python runs/h3/sfx_mix.py --video outputs/video_45.mp4 \
      --music input/男-少年气.mp3 --music-db -12 \
      --events "2.5:door.wav:-3, 4.0:step.wav:-6" \
      --out outputs/video_49_sfx.mp4

events 格式: 开始秒:音效文件:dB, 逗号分隔；未给 --music/--events 时仅保留原音轨(loudnorm)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _dur(media: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(media)], capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def mix_sfx(video: Path, out: Path, music: str = "", music_db: float = -12.0,
            events: str = "") -> Path:
    """三路混音：原音轨 + 音乐底轨 + 分段音效事件。输入无音轨时自动只混 music/events。"""
    video = Path(video)
    out = Path(out)
    if not video.is_file():
        raise ValueError(f"输入视频不存在: {video}")
    events_list: list = []
    if events:
        for part in str(events).split(","):
            part = part.strip()
            if not part:
                continue
            seg = part.split(":", 2)
            if len(seg) != 3:
                raise ValueError(f"事件格式错误: {part!r}（应为 开始秒:文件:dB）")
            t, f, db = float(seg[0]), seg[1].strip(), float(seg[2])
            if not Path(f).is_file() or _dur(Path(f)) <= 0:
                raise ValueError(f"音效文件无效: {f}")
            events_list.append((t, f, db))
    music_file = Path(music).expanduser() if music else None
    if music_file is not None and not music_file.is_file():
        raise ValueError(f"音乐文件不存在: {music_file}")

    # 探测原视频是否有音轨（-map 0:a? 失败=无音轨）
    has_audio = True
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, timeout=30)
        has_audio = bool(r.stdout.strip())
    except Exception:  # noqa: BLE001
        has_audio = True

    n_extra = int(bool(music_file)) + len(events_list)
    if n_extra == 0:
        # 无附加轨：仅 loudnorm 重建（保持时长）
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                            "-af", "loudnorm=I=-14:TP=-1.0:LRA=11", "-c:v", "copy",
                            "-c:a", "aac", "-b:a", "192k", str(out)],
                           capture_output=True, text=True, timeout=3600)
        if r.returncode != 0 or not out.is_file():
            raise ValueError("音轨重建失败: " + (r.stderr or "")[-300:])
        return out

    inputs = ["-i", str(video)]
    filters: list = []
    labels: list = []
    # 主输入音轨: index 0 (若存在)，否则用音乐当主轨? 保留原音轨为主轨：
    if has_audio:
        filters.append("[0:a]aformat=sample_rates=48000:channel_layouts=stereo[m0]")
        labels.append("[m0]")
    idx = 1
    if music_file is not None:
        inputs += ["-i", str(music_file)]
        filters.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                       f"volume={music_db}dB[m{idx}]")
        labels.append(f"[m{idx}]")
        music_idx = idx
        idx += 1
    else:
        music_idx = None
    for ei, (t, f, db) in enumerate(events_list):
        inputs += ["-i", f]
        ms = int(round(t * 1000))
        filters.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                       f"volume={db}dB,adelay={ms}|{ms}[e{ei}]")
        labels.append(f"[e{ei}]")
        idx += 1
    labels_filter = "".join(labels)
    mix = (f"{labels_filter}amix=inputs={len(labels)}:duration=longest:"
           f"dropout_transition=0:normalize=0")
    if music_idx is not None:
        # 音乐轨 3s 淡入 3s 淡出(自然过渡)
        filters.append(f"[m{music_idx}]afade=t=in:st=0:d=3,afade=t=out:st={max(0.0, _dur(music_file)-3):.2f}:d=3[mf]")
        # 替换 label 引用
        mix = mix.replace(f"[m{music_idx}]", "[mf]")
        filters[-1] = f"[m{music_idx}]afade=t=in:st=0:d=3,afade=t=out:st=0:d=0[mf]|unused" if False else filters[-1]
    filters.append(mix + ",loudnorm=I=-14:TP=-1.0:LRA=11[outa]")
    tmp = out.with_name(out.stem + "_s" + out.suffix)
    cmd = ["ffmpeg", "-y", "-v", "error"] + inputs + [
        "-map", "0:v", "-map", "[outa]", "-c:v", "copy",
        "-filter_complex", ";".join(filters), "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not tmp.is_file():
        raise ValueError("音效混音失败: " + (r.stderr or "")[-400:])
    tmp.replace(out)
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="音效链混音（音乐底轨+音效事件+原音轨）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--music", default="", help="音乐/底轨文件")
    ap.add_argument("--music-db", type=float, default=-12.0)
    ap.add_argument("--events", default="", help='开始秒:音效文件:dB,逗号分隔')
    args = ap.parse_args(argv)
    p = mix_sfx(Path(args.video), Path(args.out), music=args.music,
                music_db=args.music_db, events=args.events)
    print(f"SFX_OUT: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
