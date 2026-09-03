#!/usr/bin/env python3
"""
文生图（H3 模型版）— 用 MiniMax H3 视频模型生成 5 帧图片，取首帧

Spark 只有 H3 视频模型，没有 SD/SDXL。本脚本复用 H3 模型生成极短视频（5 帧），
保存为图片序列。文件名以 --output 为前缀。

Usage:
    python h3_text2img.py --prompt "a cute dog" --output goodboy
    python h3_text2img.py --prompt "赛博朋克城市" --output goodboy --resolution 480p
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# 允许以脚本直接运行（python runs/h3_text2img.py）：把 runs/ 加入路径后复用 h3 包
_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))
from h3 import logutil  # noqa: E402

COMFYUI_URL = os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188')

UNET_NAME = 'minimax_h3_fl2va_pruned_int8_convrot.safetensors'
CLIP_NAME = 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'
VAE_NAME = 'minimax_h3_video_vae_fp16.safetensors'

RESOLUTION_PRESETS = {
    '360p': (608, 352),
    '480p': (864, 480),
    '540p': (960, 544),
    '720p': (1280, 736),
    '768p': (1344, 768),
}


def build_workflow(prompt: str, negative_prompt: str, width: int, height: int,
                   steps: int, seed: int, filename_prefix: str) -> dict:
    """构建 H3 最小化文生图工作流（5 帧，无音频）"""
    wf = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": UNET_NAME,
                "weight_dtype": "default"
            }
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": CLIP_NAME,
                "type": "minimax"
            }
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": VAE_NAME
            }
        },
        "5": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {
                "clip": ["2", 0],
                "vae": ["3", 0],
                "prompt": prompt,
                "width": width,
                "height": height,
                "length": 5
            }
        },
        "6": {
            "class_type": "BasicGuider",
            "inputs": {
                "model": ["1", 0],
                "conditioning": ["5", 0]
            }
        },
        "7": {
            "class_type": "KSamplerSelect",
            "inputs": {
                "sampler_name": "res_multistep"
            }
        },
        "8": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["1", 0],
                "scheduler": "simple",
                "steps": steps,
                "denoise": 1.0
            }
        },
        "9": {
            "class_type": "RandomNoise",
            "inputs": {
                "noise_seed": seed
            }
        },
        "10": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["9", 0],
                "guider": ["6", 0],
                "sampler": ["7", 0],
                "sigmas": ["8", 0],
                "latent_image": ["5", 1]
            }
        },
        "11": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["10", 0],
                "vae": ["3", 0]
            }
        },
        "12": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["11", 0],
                "filename_prefix": filename_prefix
            }
        }
    }

    if negative_prompt:
        wf["5"]["inputs"]["negative_prompt"] = negative_prompt

    return wf


def queue_prompt(workflow: dict) -> str:
    data = json.dumps({'prompt': workflow}).encode('utf-8')
    req = urllib.request.Request(
        f'{COMFYUI_URL}/prompt',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        return result.get('prompt_id')


def wait_for_completion(prompt_id: str, timeout: int = 600) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f'{COMFYUI_URL}/history/{prompt_id}') as resp:
                history = json.loads(resp.read())
                if prompt_id in history:
                    return history[prompt_id]
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError(f'任务 {prompt_id} 超时 ({timeout}s)')


def main():
    parser = argparse.ArgumentParser(description='H3 文生图（5 帧）')
    parser.add_argument('--prompt', required=True, help='正向提示词')
    parser.add_argument('--negative', default='', help='负向提示词')
    parser.add_argument('--output', default='goodboy', help='输出文件名前缀')
    parser.add_argument('--resolution', default='360p', choices=RESOLUTION_PRESETS.keys())
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--seed', type=int, default=-1)
    parser.add_argument('--dry-run', action='store_true', help='只打印工作流不提交')
    args = parser.parse_args()

    if args.seed == -1:
        args.seed = int(time.time()) % (2**32)

    width, height = RESOLUTION_PRESETS[args.resolution]

    # 运行日志（h3 系列统一格式；PS 注入 H3_LOG_FILE 则汇入会话日志）
    logutil.ensure_run_log(Path(__file__).resolve().parent.parent, 'h3_text2img')
    logutil.log_event('h3_text2img', logutil.fmt(
        event='task', argv=sys.argv[1:], resolution=args.resolution,
        frames=5, steps=args.steps, seed=args.seed,
        dry_run=bool(args.dry_run)))

    workflow = build_workflow(
        prompt=args.prompt,
        negative_prompt=args.negative,
        width=width,
        height=height,
        steps=args.steps,
        seed=args.seed,
        filename_prefix=args.output
    )

    if args.dry_run:
        logutil.log_event('h3_text2img', logutil.fmt(
            event='dry_run', nodes=len(workflow)))
        print('[DRY-RUN] H3 文生图工作流 JSON:')
        print(json.dumps(workflow, indent=2, ensure_ascii=False))
        return 0

    print(f'[INFO] 提交 H3 文生图任务到 {COMFYUI_URL}')
    print(f'[INFO] 提示词: {args.prompt[:100]}')
    print(f'[INFO] 分辨率: {width}x{height} ({args.resolution}), 帧数: 5, 步数: {args.steps}')
    print(f'[INFO] 输出前缀: {args.output}')
    print(f'[INFO] 模型: {UNET_NAME}')

    try:
        prompt_id = queue_prompt(workflow)
        print(f'[INFO] 任务已提交: {prompt_id}')
        logutil.log_event('h3_text2img', logutil.fmt(
            event='submitted', prompt_id=prompt_id))
        print('[INFO] H3 模型较大，生成可能需要 2-5 分钟...')

        result = wait_for_completion(prompt_id)

        if result.get('status', {}).get('status_str') == 'success':
            outputs = result.get('outputs', {})
            frame_count = 0
            for node_id, node_output in outputs.items():
                if 'images' in node_output:
                    for img in node_output['images']:
                        frame_count += 1
                        print(f'[OK] 图片已保存: {img.get("subfolder", "")}/{img.get("filename", "unknown")}')
            logutil.log_event('h3_text2img', logutil.fmt(
                event='completed', prompt_id=prompt_id, frames=frame_count,
                prefix=args.output))
            print('[OK] 生成完成！共 5 帧图片（取第一帧即可）')
            return 0
        else:
            status = result.get('status', {})
            logutil.log_event('h3_text2img', logutil.fmt(
                event='err', prompt_id=prompt_id, reason='task_failed'))
            print(f'[ERROR] 任务失败: {status.get("messages", result)}')
            return 1

    except urllib.error.URLError as e:
        logutil.log_event('h3_text2img', logutil.fmt(
            event='err', reason='comfy_unreachable', detail=str(e)[:200]))
        print(f'[ERROR] 无法连接 ComfyUI ({COMFYUI_URL}): {e}')
        print('[HINT] 确保 ComfyUI 正在运行: tmux attach -t comfyui')
        return 2
    except Exception as e:
        logutil.log_event('h3_text2img', f'err {e}')
        print(f'[ERROR] {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
