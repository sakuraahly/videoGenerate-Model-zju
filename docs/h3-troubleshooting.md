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
(ComfyUI 本环境**自 2026-09-03 起是 systemd 服务 `comfyui.service`**，日志用 journalctl；
历史上是 tmux/裸进程，判断一律按端口探测 `ss -ltn | grep :8188`):
```bash
# 看 systemd 服务日志（sudo 只能人工交互执行）
ssh spark 'journalctl -u comfyui.service --no-pager | tail -n 100'
# 或看 tmux 会话输出（若确为 tmux 形态）
ssh spark 'tmux capture-pane -pt comfyui -S -200 2>/dev/null || echo "无 tmux 会话"'
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

> ⚠️ 2026-09-03 的重要澄清：本环境曾出现“任务提交后长时间无响应”的假卡死。
> 查证后发现客户端格式**没有问题**——真正原因是 ① ComfyUI 以 `--enable-manager` 启动，
> 启动后向 GitHub 拉取列表超时（journal 大量 `asyncio TimeoutError` /
> `switching to local mode`，可达 ~7 分钟）；② 个别任务本身执行极慢
> （实测一次 360p/5s i2v 从提交到出片 **~101 分钟**，客户端 timeout=3600s 先放弃，
> 但 ComfyUI 实际完成并产出 mp4，见 `docs/session-summary.md §12`）。
> 所以看到“卡住”时：先看 ComfyUI 是否仍在执行（`system_stats` 的 `queue_remaining`），
> 再对比 journal 的 `Prompt executed in …` 与提交时间；客户端超时后**无参数重跑
> h3_submit 会自动续传**，不会重复生成。

```bash
# Clear the queue
ssh spark 'curl -s -X POST http://127.0.0.1:8188/interrupt'

# Restart ComfyUI if needed（现行 = systemd 服务 comfyui.service；sudo 需人工交互密码）
ssh spark 'sudo systemctl restart comfyui.service'   # 人工在 spark 终端执行
# 历史（tmux 形态，仅供参考）：
ssh spark 'pkill -f "main.py --listen 127.0.0.1 --port 8188"; sleep 3; tmux new-session -d -s comfyui "cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch"'
```
