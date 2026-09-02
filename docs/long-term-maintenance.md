# Long-Term Maintenance & Sustainability Guide

> **Note**: per-run audit is now automatic — every generation writes
> `workflows/h3_*/job.json` (stage, params, prompt_id, remote path, status, timestamps),
> and breakpoints live in `last_job.json`. This file's run-logging section remains useful
> for extra analytics; the cleanup guidance below is still current.
> See also `docs/user-guide.md` and `docs/robustness-and-modularity.md`.

This document covers practices and infrastructure for keeping the H3 video generation pipeline healthy and efficient over time.

---

## 1. Run Logging

Every generation should be logged to `runs/generation-log.jsonl` for traceability and debugging.

**Fields to log:**
```json
{
  "timestamp": "ISO-8601",
  "prompt_id": "uuid",
  "user_prompt": "original user request",
  "engineered_prompt": "final prompt sent to model",
  "width": 864,
  "height": 480,
  "length": 124,
  "seed": 12345,
  "duration_sec": 287,
  "gpu_peak_mb": 36291,
  "output_file": "MiniMax_H3_00005_.mp4",
  "status": "success|error",
  "error_message": null
}
```

**Why**: Enables pattern analysis (which prompts succeed, average generation times, GPU memory trends). Without logs, debugging regressions after model updates is impossible.

---

## 2. Output Cleanup

ComfyUI accumulates output files indefinitely. Set up periodic cleanup:

### Manual cleanup:
```bash
# List by age
ssh spark 'ls -lht ~/ai/ComfyUI/output/video/ | head -20'

# Delete files older than 30 days
ssh spark 'find ~/ai/ComfyUI/output/video/ -name "*.mp4" -mtime +30 -delete'
```

### Automated (cron on Spark):
```bash
# Add to crontab on spark:
ssh spark 'crontab -e'
# Add line:
0 3 * * 0 find ~/ai/ComfyUI/output/video/ -name "*.mp4" -mtime +30 -delete
```

### Important outputs:
Download valued outputs to local machine or cloud storage before cleanup. The `scp` download in the submission script is the retention boundary — once downloaded locally, the remote copy is disposable.

---

## 3. ComfyUI Update Management

ComfyUI updates frequently. H3 nodes live in `comfy_extras.nodes_minimax_h3` (built-in), so updates generally preserve H3 support. But always:

1. **Before updating**: Note the current working commit
   ```bash
   ssh spark 'cd ~/ai/ComfyUI && git log --oneline -1'
   ```

2. **Update**:
   ```bash
   ssh spark 'cd ~/ai/ComfyUI && git pull && pip install -r requirements.txt'
   ```

3. **Verify**: Run the preflight check (see `skills/h3-video-generation.md`)

4. **Rollback** if broken:
   ```bash
   ssh spark 'cd ~/ai/ComfyUI && git checkout <previous-commit>'
   ```

---

## 4. Model Versioning

When MiniMax releases updated model weights:

1. Download the new model alongside the old one (don't overwrite)
2. Update `workflows/h3-flat-template.json` with the new filename
3. Run a test generation with the same seed and prompt for comparison
4. If quality improved, delete the old model; otherwise keep both

**Document model versions** in `docs/model-versions.md`:
```markdown
| Version | File | Date Added | Notes |
|---|---|---|---|
| v1.0 | minimax_h3_fl2va_pruned_int8_convrot.safetensors | 2026-09-01 | Initial, working |
```

---

## 5. Health Check Automation

Create a daily health check script that runs via cron:

```bash
#!/bin/bash
# ~/h3-healthcheck.sh on spark

COMFYUI_URL="http://127.0.0.1:8188"

# Check service
if ! systemctl --user is-active --quiet comfyui; then
    echo "ALERT: ComfyUI not running"
    systemctl --user start comfyui
    exit 1
fi

# Check API
if ! curl -sf "$COMFYUI_URL/system_stats" > /dev/null; then
    echo "ALERT: ComfyUI API not responding"
    exit 1
fi

# Check models
for model in \
    models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
    models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
    models/vae/minimax_h3_video_vae_fp16.safetensors \
    models/vae/minimax_h3_audio_vae_fp32.safetensors; do
    if [ ! -f ~/ai/ComfyUI/$model ]; then
        echo "ALERT: Missing model $model"
        exit 1
    fi
done

# Check node registration
if ! curl -sf "$COMFYUI_URL/object_info/MiniMaxH3ImageToVideo" | grep -q "MiniMaxH3ImageToVideo"; then
    echo "ALERT: H3 nodes not registered"
    exit 1
fi

echo "OK"
```

---

## 6. Prompt Files（当前约定，非历史规划）

仓库当前只用**固定两个文件**（自动化默认读取）：

```
prompts/positive_prompts.txt   # 生成用正向提示词（必填）
prompts/negative_prompts.txt   # 负向提示词（缺失时按空处理）
```

早前文档曾设想按主题拆分“提示词库”（如 `classroom-teacher-writing.md` 等），该结构
**未落地**，不再承诺。若你要按场景维护多份提示词：

- 新建文件如 `prompts/story_a.txt`，运行时指定：
  `python runs\h3_submit.py --prompt-file prompts\story_a.txt`；
- 或修改 `config\pipeline.json` 中某 stage 的 `prompt_files.positive` 指向该文件，
  以后 `--stage 该阶段` 即用该提示词；
- 每次提交的 prompt 快照/参数会随 `workflows\h3_*\job.json` 自动留存，供质量分析，
  无需另写 `runs/generation-log.jsonl`（可选，见第 1 节）。

---

## 7. SSH Tunnel Persistence

SSH tunnels drop when the network changes or the connection times out. For persistent access:

### Option A: autossh (auto-reconnect)
```bash
# Install locally
autossh -M 0 -N -L 8188:127.0.0.1:8188 spark -o "ServerAliveInterval=30" -o "ServerAliveCountMax=3"
```

### Option B: systemd service (on local machine)
Create `~/.config/systemd/user/comfyui-tunnel.service`:
```ini
[Unit]
Description=ComfyUI SSH Tunnel
After=network.target

[Service]
ExecStart=/usr/bin/ssh -N -L 8188:127.0.0.1:8188 spark -o ServerAliveInterval=30
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

---

## 8. Batch Generation

For generating multiple videos in sequence (在 Windows 本机执行；提示词文件按需自建目录，
如 `prompts/batch/`）：

```powershell
# PowerShell 示例（或把每条做成任务）：提示词文件存于 prompts\batch\<name>.txt
foreach ($f in Get-ChildItem "prompts\batch\*.txt") {
    Write-Host "=== Generating: $($f.BaseName) ==="
    python runs\h3_submit.py --prompt-file $f.FullName --output "outputs\$($f.BaseName)"
    Start-Sleep -Seconds 30   # 冷却，防过热
}
```

Add 30-second cooldowns between generations to prevent thermal throttling.

---

## 9. Disk Space Monitoring

Model files + outputs consume significant disk space on Spark:

```bash
# Check disk usage
ssh spark 'df -h ~ | tail -1'

# Check ComfyUI directory sizes
ssh spark 'du -sh ~/ai/ComfyUI/models/ ~/ai/ComfyUI/output/'
```

Set up alerts if disk usage exceeds 80%.

---

## 10. Backup Strategy

Critical files to back up:
- `runs/h3_submit.py` + `runs/h3/` — 本机编排 CLI 与包
- `shell/`、`*.bat`、`config/` — 自动化脚本与配置（含 6 个工作流路径/阶段）
- `skills/` — prompt engineering knowledge
- `prompts/` — 当前使用的正向/负向提示词（及你自建的多份提示词）
- Any high-value output videos

These are all in the git repository and should be committed regularly. Model files are NOT backed up (re-downloadable from HuggingFace).
