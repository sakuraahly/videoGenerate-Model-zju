# H3 Video Generation — Troubleshooting

> **Tip**: most day-to-day runs go through the automated pipeline (`bats\generate\menu.bat` /
> `shell/generate_video.ps1`), which already (a) refuses UI-format/subgraph workflows,
> (b) validates flat API templates & placeholders, (c) retries network hiccups and resumes
> from breakpoints. Run `bats\generate\menu.bat → [5]` for a full environment/model report first.
> See `docs/user-guide.md` and `docs/robustness-and-modularity.md`.

## Error: `Node '4c314f31-ecda-4b08-ae98-faaba1bf613f' not found`

**Cause**: The default workflow `first-h3.json` uses a subgraph (group node) with UUID type. ComfyUI's `/prompt` API does not resolve subgraph definitions — it treats the UUID as a node class type and fails.

**Fix**: Use the flat workflow template instead. Either:
1. Use `workflows/h3-flat-template.json` directly
2. Use `runs/h3_submit.py` which builds the flat graph programmatically

**Prevention**: Never submit the raw UI-format workflow from `~/ai/ComfyUI/user/default/workflows/` via the API. Always flatten subgraphs first.

---

## Error: `missing_node_type` for a known node

**Cause**: ComfyUI hasn't loaded the node module, usually because:
- ComfyUI was just restarted and is still loading
- A custom node package is missing

**Fix**:
```bash
# Check ComfyUI is fully loaded
ssh spark 'curl -s http://127.0.0.1:8188/object_info/MiniMaxH3ImageToVideo | head -c 100'
```
If empty or error, wait 30 seconds and retry. If still failing, check ComfyUI logs
(ComfyUI 在本环境是 **手动/tmux 进程，不是 systemd 服务**；只有你确实以 systemd
运行时才改用 `journalctl --user -u comfyui ...`):
```bash
# 看 tmux 会话输出（本套程序/文档约定的会话名为 comfyui）
ssh spark 'tmux capture-pane -pt comfyui -S -200 2>/dev/null || echo "无 tmux 会话；若手动启动请查看你的启动终端/日志文件"'
```

---

## Error: `CUDA out of memory` or generation hangs

**Cause**: The model requires ~36 GB VRAM. Another process may be using GPU memory.

**Fix**:
```bash
# Check what's using GPU
ssh spark 'nvidia-smi --query-compute-apps=pid,used_gpu_memory,name --format=csv,noheader'

# Kill stale processes (be careful!)
ssh spark 'kill <PID>'
```

---

## Error: `Connection refused` on port 8188

**Cause**: ComfyUI is not running.

**Fix**:
```bash
# ComfyUI 是手动/tmux 进程：用 tmux 启动（自动化入口亦可：本机 bats\generate\menu.bat → [1]
# 会自动检查/启动远程 ComfyUI）
ssh spark 'tmux new-session -d -s comfyui "cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch"'
# Wait 10s
ssh spark 'curl -s http://127.0.0.1:8188/system_stats | head -c 100'
```

---

## Generation produces garbled Chinese text (乱码)

**Cause**: H3's text rendering has inherent limitations for CJK characters. The model was primarily trained on English text.

**Mitigation**:
1. Use explicit character-by-character enumeration (see prompt engineering guide)
2. Specify the font/script style: `regular script (楷体)`
3. Keep text short — max 5-6 characters
4. Describe the physical act of writing (hand, chalk, stroke order)
5. Accept that some distortion is likely; use post-production text overlay if exact text is critical

---

## Video has no audio

**Cause**: The prompt didn't describe audio, or the audio VAE failed to decode.

**Fix**: Always include audio description in the prompt:
```
Natural classroom ambience: chalk scratching on board, distant birds chirping outside.
```

Verify audio VAE is loaded (node 4 in the workflow).

---

## Generation is very slow (>10 minutes for 5 seconds)

**Normal range**: 4-6 minutes on GB10 for 864x480 @ 124 frames.

If slower:
```bash
# Check if GPU is throttled
ssh spark 'nvidia-smi --query-gpu=clocks.current.graphics,clocks.current.memory,temperature.gpu --format=csv,noheader'

# Check for thermal throttling
ssh spark 'cat /sys/class/thermal/thermal_zone0/temp'
```

---

## Output video is corrupted / won't play

**Fix**: Try saving with explicit format:
- Change `format` from `"auto"` to `"mp4"` in SaveVideo node
- Change `codec` from `"auto"` to `"h264"` with `encoding: "re-encode"`

---

## SSH connection drops during generation

**Cause**: Long-running SSH commands may timeout.

**Fix**: 优先使用本机自动化（`bats\generate\run.bat` / `bats\generate\menu.bat [1]`）——它自带隧道自愈与断点续传
（--resume），ssh 断开不会丢任务。**不要把 `runs/h3_submit.py` scp 到 spark 运行**：
它是本机编排 CLI（依赖本地 `runs/h3/` 包与隧道）。确需纯远程提交时，用 curl 放进 tmux：
```bash
ssh spark 'tmux new -d "curl -sf -X POST http://127.0.0.1:8188/prompt -H \"Content-Type: application/json\" -d @/tmp/workflow.json > /tmp/h3_submit.log 2>&1"'
# Check later:
ssh spark 'cat /tmp/h3_submit.log'
```

---

## ComfyUI queue is stuck

```bash
# Clear the queue
ssh spark 'curl -s -X POST http://127.0.0.1:8188/interrupt'

# Restart ComfyUI if needed（手动/tmux 进程；若确为 systemd 服务才用 systemctl）
ssh spark 'pkill -f "main.py --listen 127.0.0.1 --port 8188"; sleep 3; tmux new-session -d -s comfyui "cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch"'
```
