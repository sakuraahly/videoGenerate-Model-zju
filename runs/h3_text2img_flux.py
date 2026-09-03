#!/usr/bin/env python3
"""
h3_text2img_flux — 用 spark ComfyUI 的 FLUX.1-dev 生成本地文生图（1344x768 档）。
产物自动落到 spark ~/ai/ComfyUI/input/<name>.png（供 i2v/r2v/flf2v 作参考图）并下载到本地。

用法：
  python runs/h3_text2img_flux.py --text "..." --name hero_night --width 1344 --height 768
可选：--steps 28 --seed 12345 --prefix hero_ref（spark output 文件名前缀）
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # runs/
from h3 import comfy  # noqa: E402

REMOTE_HOST = "spark"
COMFY = "http://127.0.0.1:8188"


def build_flux_workflow(text: str, width: int, height: int,
                        steps: int, seed: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "clip_l.safetensors",
                         "clip_name2": "t5xxl_fp16.safetensors", "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": text, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "", "clip": ["2", 0]}},   # FLUX 无负面：空文本
        "6": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps,
                         "cfg": 1.0, "sampler_name": "euler",
                         "scheduler": "simple", "denoise": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--name", required=True, help="产物名：spark input/<name>.png + 本地 refs/<name>.png")
    ap.add_argument("--width", type=int, default=1344)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--prefix", default="flux_ref")
    args = ap.parse_args()

    client = comfy.ComfyClient(COMFY, retries=2)
    wf = build_flux_workflow(args.text, args.width, args.height, args.steps, args.seed, args.prefix)
    print(f"[flux] submitting {args.width}x{args.height} steps={args.steps} seed={args.seed}")
    try:
        prompt_id = client.submit(wf)
    except comfy.ComfyRejected as e:
        print(f"[flux] 提交被拒: {e}", file=sys.stderr)
        if getattr(e, "body", None):
            print(e.body[:1500], file=sys.stderr)
        return 3
    print(f"[flux] prompt_id={prompt_id} 轮询中（FLUX 单图约 2-6 分钟）...")
    kind, entry = client.wait_for(prompt_id, timeout=1800)
    if kind == "timeout":
        print("[flux] 超时", file=sys.stderr)
        return 2
    if kind == "error" or (entry and (entry.get("status") or {}).get("status_str") == "error"):
        print("[flux] 任务失败", file=sys.stderr)
        return 3
    # 定位 SaveImage 输出
    outs = (entry or {}).get("outputs") or {}
    images = []
    for node_out in outs.values():
        for im in (node_out.get("images") or []):
            if isinstance(im, dict) and im.get("filename"):
                images.append(im)
    if not images:
        print("[flux] 未找到输出图片", file=sys.stderr)
        return 2
    im = images[0]
    remote = f"{im['filename']}" if im.get("subfolder") in (None, "", " ") else \
        f"{im['subfolder']}/{im['filename']}"
    print(f"[flux] spark output: ~/ai/ComfyUI/output/{remote}")

    # 落 spark input（供视频模板 LoadImage 引用）
    dest_input = f"~/ai/ComfyUI/input/{args.name}.png"
    subprocess.run(["ssh", "-o", "BatchMode=yes", REMOTE_HOST,
                    f"cp ~/ai/ComfyUI/output/{remote} {dest_input}"], check=False)
    print(f"[flux] copied to spark input: {dest_input}")

    # 下载本地 refs\
    local_dir = Path.cwd() / "refs"
    local_dir.mkdir(exist_ok=True)
    local = local_dir / f"{args.name}.png"
    r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes",
                        f"{REMOTE_HOST}:~/ai/ComfyUI/output/{remote}", str(local)])
    if r.returncode == 0 and local.exists():
        print(f"[flux] 本地副本: {local}（{local.stat().st_size} B）")
    else:
        print("[flux] scp 下载失败（可稍后手动 scp spark:... 补下）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
