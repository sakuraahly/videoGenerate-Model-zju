# H3 Video Generation — Manual Operations Guide

> **Note (migration)**: this guide documents the low-level manual SSH path from before the
> automation existed. For day-to-day one-click generation use **`bats\generate\menu.bat` / `bats\generate\run.bat`**
> (see `docs/user-guide.md`; architecture in `docs/robustness-and-modularity.md`).
> Keep this file for debugging or when you must operate the remote by hand.

This guide walks through generating a video with MiniMax H3 on DGX Spark step by step. Copy-paste every command.

---

## Prerequisites

- SSH access to the DGX Spark (configured in `~/.ssh/config` as host `spark`)
- ComfyUI running on Spark as a manual background process (see `docs/comfyui-startup-and-access.md`)
- All 4 model files downloaded (see architecture doc)

---

## Step 1: Verify SSH Connectivity

```bash
ssh spark 'echo "connected"'
```

Expected output: `connected`

If this fails, check your SSH key and config.

---

## Step 2: Check ComfyUI Is Running

> ComfyUI on Spark runs as a manual background process (not a systemd service).
> Full startup / tunnel procedure: see `docs/comfyui-startup-and-access.md`.

```bash
ssh spark "pgrep -af main.py && ss -tlnp | grep 8188"
```

Expected: one line showing `~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 ...`
and a `LISTEN` line on `127.0.0.1:8188`.

If not running, start it via tmux (recommended):
```bash
ssh spark "tmux new-session -d -s comfyui 'cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 12'"
```

Wait ~10 seconds, then verify with `curl -s http://127.0.0.1:8188/system_stats`.

---

## Step 3: Check GPU Availability

```bash
ssh spark 'nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader'
```

Expected: GPU utilization near 0%, low memory usage. If another process is using >30 GB, wait for it to finish.

---

## Step 4: Open SSH Tunnel (for Web UI Access)

On your **local machine**, open a new terminal:

```bash
ssh -L 8188:127.0.0.1:8188 spark
```

Keep this terminal open. Now you can open `http://localhost:8188` in your browser to access the ComfyUI web interface.

---

## Step 5: Verify Models Exist

```bash
ssh spark 'ls -lh ~/ai/ComfyUI/models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors ~/ai/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors ~/ai/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors ~/ai/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors'
```

Expected: All 4 files listed with sizes. If any are missing, download them from HuggingFace (see architecture doc for URLs).

---

## Step 6: Prepare Your Prompt

Write your scene description following the prompt engineering rules. Example:

```
A five-second cinematic shot in a quiet, well-lit classroom.
Medium close-up of a teacher's back and right hand as they slowly write
Chinese characters on a dark green chalkboard with white chalk.
The characters appear one by one in clear, standard regular script (楷体):
first '你', then '好', then a comma '，', then '朋', then '友',
forming the complete phrase '你好，朋友'.
The camera holds steady with slight handheld movement.
Natural classroom ambience: chalk scratching on board, distant birds chirping outside.
No dialogue, no music, no cuts.
```

Save this to a file, e.g., `/tmp/my_prompt.txt`.

---

## Step 7: Submit the Generation Task

### Option A: Use the local automation (recommended; NOT the remote copy)

> 注意：`runs/h3_submit.py` 现在是**本机编排 CLI**（依赖本地 `runs/h3/` 包与 SSH 隧道），
> 把它 scp 到 spark 单文件运行已不可用。请在 Windows 本机执行：

```powershell
cd <仓库根目录>
python runs\h3_submit.py --prompt-file "D:\路径\my_prompt.txt"   # 或 ./bats\generate\run.bat / bats\generate\menu.bat [1]
```
（它会自动检查远程、建隧道、提交、轮询并打印 `REMOTE_VIDEO_PATH:`；退出码/断点
语义见 `docs/user-guide.md`。）

### Option B: Use curl directly（纯远程、手动）

```bash
# First, create the workflow JSON with your prompt
# (use the template in workflows/h3-flat-template.json and replace the prompt string)

# Then submit:
ssh spark 'curl -s -X POST http://127.0.0.1:8188/prompt \
  -H "Content-Type: application/json" \
  -d @/path/to/workflow.json'
```

Expected response:
```json
{"prompt_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}
```

Save the `prompt_id`.

---

## Step 8: Monitor Progress

Check queue status:
```bash
ssh spark 'curl -s http://127.0.0.1:8188/queue | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"running:\",len(d[\"queue_running\"]),\"pending:\",len(d[\"queue_pending\"]))"'
```

Check GPU during generation:
```bash
ssh spark 'nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader'
```

Expected: ~96% utilization, ~36 GB memory.

Generation takes ~5 minutes for 864x480 @ 124 frames.

---

## Step 9: Check Completion

Replace `YOUR_PROMPT_ID` with the actual prompt_id from Step 7:

```bash
ssh spark 'curl -s http://127.0.0.1:8188/history/YOUR_PROMPT_ID | python3 -m json.tool'
```

Look for `"status_str": "success"` and the output filename in the `outputs` section:
```json
{
  "14": {
    "images": [
      {
        "filename": "MiniMax_H3_00005_.mp4",
        "subfolder": "video",
        "type": "output"
      }
    ]
  }
}
```

---

## Step 10: Download the Video

Replace the filename with your actual output:

```bash
scp spark:~/ai/ComfyUI/output/video/MiniMax_H3_00005_.mp4 ./my_video.mp4
```

Play it locally:
```bash
# Windows
start my_video.mp4

# macOS
open my_video.mp4

# Linux
xdg-open my_video.mp4
```

---

## Step 11: List All Generated Videos

```bash
ssh spark 'ls -lht ~/ai/ComfyUI/output/video/'
```

---

## Quick Reference Card

| Action | Command |
|---|---|
| Check ComfyUI status | `ssh spark "pgrep -af main.py && ss -tlnp \| grep 8188"` |
| Start ComfyUI (tmux) | `ssh spark "tmux new-session -d -s comfyui 'cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 12'"` |
| Stop ComfyUI | `ssh spark "pkill -f 'python main.py'"` |
| Open web UI tunnel | `ssh -L 8188:localhost:8188 spark` |
| Check queue | `ssh spark 'curl -s http://127.0.0.1:8188/queue'` |
| Check GPU | `ssh spark 'nvidia-smi'` |
| View history | `ssh spark 'curl -s http://127.0.0.1:8188/history/PROMPT_ID'` |
| List outputs | `ssh spark 'ls -lht ~/ai/ComfyUI/output/video/'` |
| Download output | `scp spark:~/ai/ComfyUI/output/video/FILENAME.mp4 ./` |
| Reboot Spark | `ssh spark 'sudo systemctl reboot'` |
