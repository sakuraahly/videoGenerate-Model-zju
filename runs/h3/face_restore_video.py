#!/usr/bin/env python3
"""GFPGAN 人脸修复视频工具（v5：自适应边距+全区宽羽化泊松，无框痕）。

2026-09-08 定案：与 H3Finalize 增强工序合并——ComfyUI 节点 H3FaceRestore 经
本脚本（~/ai/tts-venv 独立环境）执行；也可引擎侧复用：
  python runs/h3/face_restore_video.py --video <v> --out <out> [--onnx <路径>] [--device cpu|auto]

依赖（tts-venv）：onnxruntime / opencv-python-headless / numpy；
人脸检测：~/ai/wav2lip/src/Wav2Lip-master 的 face_detection（s3fd；CPU）；
模型：Neus/GFPGANv1.4.onnx（默认 ~/ai/gfpgan/GFPGANv1.4.onnx）。

处理区=逐帧检测框（动态跟随），边距随人脸尺寸自适应：
  上/左/右=max(bh*0.35,24)，下缘=max(bh*0.55,40)（覆盖颌/颈/衣领）；
掩膜=全裁剪区 内缩 6%+σ10% 宽羽化后阈值 5 → cv2.seamlessClone(NORMAL_CLONE)。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ONNX_DEFAULT = Path(os.path.expanduser('~/ai/gfpgan/GFPGANv1.4.onnx'))
W2L_SRC = Path(os.path.expanduser('~/ai/wav2lip/src/Wav2Lip-master'))


def _load_onnx(onnx_path: Path):
    import onnxruntime as ort
    return ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])


def _get_detector(device: str):
    sys.path.insert(0, str(W2L_SRC))
    from face_detection import FaceAlignment, LandmarksType  # noqa: E402
    return FaceAlignment(LandmarksType._2D, flip_input=False, device=device)


def restore_frame(frame, rect, sess, inp, outp):
    """单帧：检测框 → 自适应边距 → 512 修复 → 宽羽化泊松回贴。"""
    bx1, by1, bx2, by2 = [int(v) for v in rect]
    bh = max(by2 - by1, 40)
    mt = int(max(bh * 0.35, 24)); ml = int(max(bh * 0.35, 24))
    mr = int(max(bh * 0.35, 24)); mb = int(max(bh * 0.55, 40))
    x1 = max(0, bx1 - ml); y1 = max(0, by1 - mt)
    x2 = min(frame.shape[1], bx2 + mr); y2 = min(frame.shape[0], by2 + mb)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return frame
    ch, cw = crop.shape[:2]
    crop512 = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_LINEAR)
    x = crop512.astype(np.float32) / 255.0
    x = (x - 0.5) / 0.5
    x = np.transpose(x, (2, 0, 1))[None]
    y = sess.run([outp.name], {inp.name: x})[0][0]
    y = np.transpose(y, (1, 2, 0))
    y = (y + 1.0) / 2.0
    y = np.clip(y, 0, 1) * 255.0
    y = y.astype(np.uint8)
    yres = cv2.resize(y, (cw, ch), interpolation=cv2.INTER_LINEAR)
    mask = np.zeros((ch, cw), np.uint8)
    mask[:, :] = 255
    er = max(int(min(ch, cw) * 0.06), 6)
    sigma = max(int(min(ch, cw) * 0.10), 8)
    mask = cv2.erode(mask, np.ones((er * 2 + 1, er * 2 + 1), np.uint8))
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    mask = np.where(mask > 5, 255, 0).astype(np.uint8)
    try:
        return cv2.seamlessClone(yres, frame, mask,
                                 ((x1 + x2) // 2, (y1 + y2) // 2), cv2.NORMAL_CLONE)
    except Exception:  # noqa: BLE001
        out = frame.copy()
        out[y1:y2, x1:x2] = yres
        return out


def main() -> int:
    ap = argparse.ArgumentParser('GFPGAN 人脸修复视频（自适应边距+泊松无框痕）')
    ap.add_argument('--video', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--onnx', default=str(ONNX_DEFAULT))
    ap.add_argument('--device', default='cpu', choices=['cpu', 'auto'])
    ap.add_argument('--max-frames', type=int, default=0, help='>0 时只处理前 N 帧（快速自测）')
    args = ap.parse_args()

    onnx_path = Path(os.path.expanduser(str(args.onnx)))
    if not onnx_path.is_file():
        print('[错误] ONNX 模型不存在: %s' % onnx_path, file=sys.stderr)
        return 3
    src = Path(args.video)
    out = Path(args.out)
    if not src.is_file():
        print('[错误] 视频不存在: %s' % src, file=sys.stderr)
        return 3
    out.parent.mkdir(parents=True, exist_ok=True)

    sess = _load_onnx(onnx_path)
    inp = sess.get_inputs()[0]
    outp = sess.get_outputs()[0]
    device = 'cpu' if args.device == 'cpu' else ('cuda' if __import__('torch').cuda.is_available() else 'cpu')
    detector = _get_detector(device)

    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if args.max_frames > 0:
        frames = frames[: args.max_frames]
    print('FRAMES: %d fps: %s' % (len(frames), fps), flush=True)

    tmpdir = out.parent / ('.' + out.stem + '_frames')
    tmpdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for i, frame in enumerate(frames):
        rect = detector.get_detections_for_batch(np.array([frame]))[0]
        if rect is None:
            cv2.imwrite(str(tmpdir / ('%05d.png' % i)), frame)
            continue
        restored = restore_frame(frame, rect, sess, inp, outp)
        cv2.imwrite(str(tmpdir / ('%05d.png' % i)), restored)
    print('DONE: %d elapsed: %s' % (len(frames), round(time.time() - t0, 1)), flush=True)

    import subprocess
    # 若来源为已插帧片（fps>40），按原 fps 封帧；否则按 24fps
    mux_fps = fps if float(fps) > 40 else 24.0
    r = subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-framerate', str(mux_fps),
        '-i', str(tmpdir / '%05d.png'),
        '-i', str(src),                       # 源音轨保留（2026-09-08：此前恢复片无音轨→下游 [0:a] 缺失）
        '-map', '0:v', '-map', '1:a?', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'copy', str(out)],
        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not out.exists():
        print('[错误] 封片失败: %s' % r.stderr[-300:], file=sys.stderr)
        return 4
    print('OUT: %s %d' % (out, out.stat().st_size), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
