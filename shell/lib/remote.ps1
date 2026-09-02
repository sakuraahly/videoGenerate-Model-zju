# ============================================================================
# shell/lib/remote.ps1 — 远程 ComfyUI 检查/启动
# 依赖（脚本级变量，由 generate_video.ps1 设置）：
#   $RemoteHost $RemoteComfyUIDir $RemotePython $TmuxSession $ComfyUIPort
#   $SshConnectTimeout $HealthTimeoutSeconds
# ============================================================================

function Test-RemoteComfyUI {
    ssh -o ConnectTimeout=${SshConnectTimeout} $RemoteHost `
        "pgrep -af 'main.py' | grep -q 'ComfyUI'" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Start-RemoteComfyUI {
    Write-Info "远程 ComfyUI 未运行，正在通过 tmux 启动..."
    $cmd = "tmux new-session -d -s $TmuxSession 'cd $RemoteComfyUIDir && $RemotePython main.py --listen 127.0.0.1 --port $ComfyUIPort --disable-auto-launch --reserve-vram 12'"
    ssh -o ConnectTimeout=${SshConnectTimeout} $RemoteHost $cmd 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "tmux 启动命令返回非零（$LASTEXITCODE），继续轮询确认状态..."
    }
    # 远程通过 ssh 轮询 /system_stats，最长 HealthTimeoutSeconds
    $elapsed = 0
    while ($elapsed -lt $HealthTimeoutSeconds) {
        Start-Sleep -Seconds 5
        $elapsed += 5
        ssh -o ConnectTimeout=${SshConnectTimeout} $RemoteHost `
            "curl -sS -f -m 5 http://127.0.0.1:${ComfyUIPort}/system_stats" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Info "远程 ComfyUI 启动成功（等待 ${elapsed}s）。"
            return $true
        }
        Write-Info "  等待 ComfyUI 就绪... ${elapsed}s / ${HealthTimeoutSeconds}s"
    }
    Write-ErrorExit "远程 ComfyUI 启动超时。请手动登录检查 tmux 会话：$TmuxSession"
}
