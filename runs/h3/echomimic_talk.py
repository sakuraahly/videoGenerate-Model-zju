#!/usr/bin/env python3
"""EchoMimic 原生口型集成（§15e 无框路线）：整脸由模型原生重生成，无贴皮框。

设计（2026-09-08 夜，planbook §15e）：
  1) 取视频参考帧（40% 处，含人脸）；
  2) 与 EchoMimic 内部一致地算方形裁切区（MTCNN select_face + 0.5 crop 边距 +
     crop_and_pad 正方形化）；
  3) 整帧作为 ref image 交给 infer_audio2vid_acc.py（音频驱动、加速管线、6 步），
     输出=该裁切区的 512x512 原生重渲染（整脸重生成，天然无框）；
  4) 把渲染帧按同一裁切矩形无缝克隆回原视频每帧（cv2.seamlessClone），
     背景一致时肉眼无痕；mux 台词音轨（line.wav）。

用法（spark）：
  python runs/h3/echomimic_talk.py --video <人脸源> --audio <line.wav> [--out <path>]
      [--ref-time 0.4] [--W 512] [--H 512] [--steps 6] [--fps 24] [--seed 420] [--dry-run]
依赖：~/ai/echomimic（代码+pretrained_weights）；~/ai/tts-venv（torch/diffusers/facenet_pytorch）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time as _tm
from pathlib import Path

# EchoMimic 代码/权重根（spark 专用路径；Windows 主库只做代码/文档，不运行本链）
EM_ROOT = Path(os.path.expanduser('~/ai/echomimic'))
EM_CONF_TEMPLATE = {
    'pretrained_base_model_path': './pretrained_weights/sd-image-variations-diffusers/',
    'pretrained_vae_path': './pretrained_weights/sd-vae-ft-mse/',
    'audio_model_path': './pretrained_weights/audio_processor/whisper_tiny.pt',
    'denoising_unet_path': './pretrained_weights/denoising_unet_acc.pth',
    'reference_unet_path': './pretrained_weights/reference_unet.pth',
    'face_locator_path': './pretrained_weights/face_locator.pth',
    'motion_module_path': './pretrained_weights/motion_module_acc.pth',
    'inference_config': './configs/inference/inference_v2.yaml',
    'weight_dtype': 'fp16',
}
TTS_PY = Path(os.path.expanduser('~/ai/tts-venv/bin/python3'))
FFMPEG = 'ffmpeg'


def _run(cmd, timeout=3600, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError('fail: ' + ((r.stderr or r.stdout) or '')[-800:])
    return r.stdout


def probe_duration(path: Path) -> float:
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=nk=1:nw=1', str(path)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float((r.stdout or '').strip())
    except ValueError:
        return 0.0


def select_face(det_bboxes, probs):
    """与 infer_audio2vid_acc.py 同口径：prob>0.8 里取最大脸。"""
    if det_bboxes is None or probs is None:
        return None
    filtered = [b for i, b in enumerate(det_bboxes) if probs[i] > 0.8]
    if not filtered:
        return None
    return sorted(filtered, key=lambda x: (x[3] - x[1]) * (x[2] - x[0]), reverse=True)[0]


def crop_and_pad(image, rect):
    """与 EchoMimic src/utils/util.py 同口径：矩形→正方形（越界裁边）。返回 (crop_img, new_rect)。"""
    x0, y0, x1, y1 = [int(v) for v in rect]
    h, w = image.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    width, height = x1 - x0, y1 - y0
    side = min(width, height)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    nx0 = max(0, cx - side // 2)
    ny0 = max(0, cy - side // 2)
    nx1 = min(w, nx0 + side)
    ny1 = min(h, ny0 + side)
    # 末边补齐（保持正方形；贴边饱和）
    if nx1 - nx0 < side:
        nx1 = min(w, nx0 + side)
    if ny1 - ny0 < side:
        ny1 = min(h, ny0 + side)
    out = image[ny0:ny1, nx0:nx1]
    return out, (nx0, ny0, side if nx1 - nx0 == side else nx1 - nx0,
                 side if ny1 - ny0 == side else ny1 - ny0)


def main() -> int:
    ap = argparse.ArgumentParser('EchoMimic 原生口型集成（无框）')
    ap.add_argument('--video', required=True, help='人脸源视频（近景/正面）')
    ap.add_argument('--audio', required=True, help='台词 wav（EchoMimic 驱动音频）')
    ap.add_argument('--out', default='', help='输出路径（缺省 /tmp/echomimic_out.mp4）')
    ap.add_argument('--ref-time', type=float, default=0.4,
                    help='参考帧取点：帧号比例（0-1）或秒数（>=1.5 视为秒）')
    ap.add_argument('--W', type=int, default=512)
    ap.add_argument('--H', type=int, default=512)
    ap.add_argument('--steps', type=int, default=6)
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--context-frames', type=int, default=12)
    ap.add_argument('--seed', type=int, default=420)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    src = Path(args.video)
    wav = Path(args.audio)
    if not src.is_file() or not wav.is_file():
        print('[错误] 视频/音频不存在', file=sys.stderr)
        return 3
    if args.dry_run:
        print('DRY_RUN: video=%s audio=%s W=%d H=%d steps=%d fps=%d' %
              (src.name, wav.name, args.W, args.H, args.steps, args.fps))
        print('DRY_RUN_OK')
        return 0

    import cv2
    import numpy as np

    work = Path('/tmp/echomimic_talk')
    work.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else Path('/tmp/echomimic_out.mp4')

    cap = cv2.VideoCapture(str(src))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    if not n:
        print('[错误] 视频帧数读取失败', file=sys.stderr)
        return 4
    # 参考帧
    ref_idx = int(n * args.ref_time) if args.ref_time < 1.5 else int(args.ref_time * fps)
    ref_idx = max(0, min(ref_idx, n - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, ref_idx)
    ok, ref_frame = cap.read()
    cap.release()
    if not ok or ref_frame is None:
        print('[错误] 参考帧读取失败', file=sys.stderr)
        return 4
    print('REF: frame=%d/%d fps=%.1f' % (ref_idx, n, fps), flush=True)

    # 裁切区（与 EchoMimic 内部同口径：MTCNN select_face + 0.5 crop 边距 + 正方形）。
    # facenet_pytorch 2.6.0 权重随 wheel 内置（pnet/rnet/onet.pt），spark 可离线加载。
    from facenet_pytorch import MTCNN
    det = MTCNN(image_size=320, margin=0, min_face_size=20,
                thresholds=[0.6, 0.7, 0.7], factor=0.709,
                post_process=True, device='cuda')
    det_bboxes, probs = det.detect(ref_frame)
    sel = select_face(det_bboxes, probs)
    if sel is None:
        print('[错误] 参考帧未检测到人脸（prob>0.8）', file=sys.stderr)
        return 5
    xyxy = np.round(sel[:4]).astype(int)
    rb, re, cb, ce = int(xyxy[1]), int(xyxy[3]), int(xyxy[0]), int(xyxy[2])
    r_pad_crop = int((re - rb) * 0.5)
    c_pad_crop = int((ce - cb) * 0.5)
    crop_rect = [max(0, cb - c_pad_crop), max(0, rb - r_pad_crop),
                 min(ce + c_pad_crop, ref_frame.shape[1]), min(re + r_pad_crop, ref_frame.shape[0])]
    _, square_rect = crop_and_pad(ref_frame, crop_rect)
    x0, y0, sw, sh = square_rect
    print('CROP: rect=%s square=(%d,%d,%dx%d)' % (crop_rect, x0, y0, sw, sh), flush=True)

    # 写入 EchoMimic 运行配置（参考图=整帧；EchoMimic 内部复现同一裁切）
    ref_img = work / 'ref.png'
    cv2.imwrite(str(ref_img), ref_frame)
    conf = dict(EM_CONF_TEMPLATE)
    conf['test_cases'] = {str(ref_img): [str(wav)]}
    import json
    cfg = work / 'em_run.yaml'
    with open(cfg, 'w', encoding='utf-8') as f:
        f.write('# auto-generated by echomimic_talk.py\n')
        for k, v in conf.items():
            f.write('%s: %s\n' % (k, json.dumps(v, ensure_ascii=False)))

    # 跑 EchoMimic（显式指定大帧数上限；pipeline 会按音频长度截断）
    r = subprocess.run(
        [str(TTS_PY), str(EM_ROOT / 'infer_audio2vid_acc.py'), '--config', str(cfg),
         '-W', str(args.W), '-H', str(args.H), '--fps', str(args.fps), '-L', '1200',
         '--steps', str(args.steps), '--context_frames', str(args.context_frames),
         '--seed', str(args.seed), '--device', 'cuda'],
        capture_output=True, text=True, timeout=7200, cwd=str(EM_ROOT))
    print(r.stdout[-800:], flush=True)
    if r.returncode != 0:
        print('[错误] EchoMimic 退出码 %d: %s' % (r.returncode, (r.stderr or '')[-600:]), file=sys.stderr)
        return 6
    # 解析 *_withaudio.mp4 输出
    cand = [l.strip() for l in (r.stdout or '').splitlines()
            if l.strip().endswith('_withaudio.mp4')]
    if not cand:
        print('[错误] 未解析到 EchoMimic 输出路径', file=sys.stderr)
        print(r.stdout[-1500:], file=sys.stderr)
        return 7
    em_out = Path(cand[-1])
    print('EM_OUT: %s' % em_out.name, flush=True)

    # 回贴：渲染帧 512² -> 裁切方形 -> seamlessClone 回原帧；音轨=line.wav
    # （渲染帧数=音频帧数；源视频长于台词时逐帧对应，长出的部分保留原帧+克隆尾帧兜底）
    os.makedirs(str(work / 'frames_out'), exist_ok=True)
    # 先读全部渲染帧与源帧
    rcap = cv2.VideoCapture(str(em_out))
    rn = int(rcap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if not rn:
        print('[错误] 渲染帧读取失败', file=sys.stderr)
        return 8
    sc = cv2.VideoCapture(str(src))
    idx = 0
    while idx < rn:
        rok, rf = rcap.read()
        sok, sf = sc.read()
        if not sok:
            # 源帧不足：克隆最后一帧（不再重读）
            cap2 = cv2.VideoCapture(str(src))
            cap2.set(cv2.CAP_PROP_POS_FRAMES, max(0, n - 1))
            sok, sf = cap2.read()
            cap2.release()
        if not rok:
            break
        if not sok:
            break
        pat = cv2.resize(rf, (int(square_rect[2]), int(square_rect[3])),
                         interpolation=cv2.INTER_AREA)
        h, w = sf.shape[:2]
        # 越界防御：裁切矩形可能触及图像边缘 → 用 alpha 羽化混合代替 seamlessClone
        if x0 >= 0 and y0 >= 0 and x0 + pat.shape[1] <= w and y0 + pat.shape[0] <= h:
            mask = np.full((pat.shape[0], pat.shape[1]), 255, np.uint8)
            try:
                sf = cv2.seamlessClone(pat, sf, mask, (x0 + pat.shape[1] // 2,
                                                       y0 + pat.shape[0] // 2),
                                       cv2.NORMAL_CLONE)
            except cv2.error:
                sf = _soft_paste(sf, pat, x0, y0)
        else:
            sf = _soft_paste(sf, pat, max(0, x0), max(0, y0))
        cv2.imwrite(str(work / 'frames_out' / '%06d.png' % idx), sf)
        idx += 1
    rcap.release()
    sc.release()
    print('COMPOSITE: %d frames' % idx, flush=True)

    # ffmpeg：png 序列 + 台词音轨 -> 成片（连帧时间=渲染帧数/设定 fps）
    _run([FFMPEG, '-y', '-loglevel', 'error',
          '-framerate', str(args.fps), '-i', str(work / 'frames_out' / '%06d.png'),
          '-i', str(wav), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
          '-c:a', 'aac', '-b:a', '192k', '-shortest', str(out)])
    print('FINAL: %s %d' % (out, out.stat().st_size), flush=True)
    # 脱敏输出（§15 边界）
    print('ECHO_TALK: %s（EchoMimic 原生口型片）' % out.name, flush=True)
    print('DONE_ECHO_TALK', flush=True)
    return 0


def _soft_paste(frame, patch, x0, y0):
    import cv2
    import numpy as np
    h, w = frame.shape[:2]
    pw, ph = patch.shape[1], patch.shape[0]
    x1, y1 = min(w, x0 + pw), min(h, y0 + ph)
    cx0, cy0 = min(x0, x1), min(y0, y1)
    sw, sh = x1 - cx0, y1 - cy0
    if sw <= 0 or sh <= 0:
        return frame
    crop = patch[:sh, :sw]
    if crop.shape[0] == 0 or crop.shape[1] == 0:
        return frame
    mask = np.zeros((sh, sw), np.uint8)
    edge = max(2, int(min(sh, sw) * 0.06))
    mask[edge:-edge, edge:-edge] = 255
    mask = cv2.GaussianBlur(mask, (0, 0), edge / 2.0)
    alpha = mask.astype(np.float32) / 255.0
    ro = frame[cy0:y1, cx0:x1].astype(np.float32)
    ro = ro * (1 - alpha[..., None]) + crop.astype(np.float32) * alpha[..., None]
    frame[cy0:y1, cx0:x1] = ro.astype(np.uint8)
    return frame


if __name__ == '__main__':
    sys.exit(main())
