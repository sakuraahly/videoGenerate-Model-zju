# Stop-ComfyUI.ps1
# 停止 spark ComfyUI 连接：先停本地 SSH 隧道进程，再停远程 ComfyUI。
# 远程部分：优先 tmux 会话；会话无效则按 main.py 命令行补杀裸进程（端口探测兜底）。

param(
    [string]$RemoteHost = "spark",
    [int]$LocalPort = 8188,
    [int]$RemotePort = 8188
)

Write-Host "[1/2] 清理本地 SSH 隧道 (端口 $LocalPort)..." -ForegroundColor Cyan

# 只停"占用该端口且是 ssh"的进程，避免误杀其它程序
$tunnelProcessIds = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -ne 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique

if ($tunnelProcessIds) {
    $stopped = 0
    $failed = @()
    foreach ($processId in $tunnelProcessIds) {
        $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq "ssh") {
            try {
                Stop-Process -Id $processId -Force -ErrorAction Stop
                Write-Host "    ✅ 已停止本地 SSH 进程 (PID: $processId)" -ForegroundColor Green
                $stopped++
            }
            catch {
                $failed += "$processId ($($proc.ProcessName))"
            }
        }
    }
    if ($failed.Count -gt 0) {
        Write-Host "    ❌ 无法停止以下占用 ${LocalPort} 的进程（可能权限不足）：" -ForegroundColor Red
        foreach ($f in $failed) { Write-Host "       PID $f" -ForegroundColor Red }
        Write-Host "       请用管理员 PowerShell 执行: taskkill /PID <pid> /F" -ForegroundColor Red
    }
    if ($stopped -eq 0 -and $failed.Count -eq 0) {
        Write-Host "    ℹ️ 端口 $LocalPort 被非 ssh 进程占用，未动它（PID: $($tunnelProcessIds -join ', ')）。" -ForegroundColor Yellow
    }
}
else {
    Write-Host "    ℹ️ 本地端口 $LocalPort 未被占用。" -ForegroundColor Yellow
}

Write-Host "[2/2] 停止远程 ComfyUI (spark, 端口 $RemotePort)..." -ForegroundColor Cyan

function Test-RemoteListening {
    $p = ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost "ss -ltn 2>/dev/null | grep -q ':${RemotePort} ' && echo UP || echo DOWN" 2>$null
    return ($LASTEXITCODE -eq 0 -and $p -match 'UP')
}

# 1) 若由 tmux 会话管理 → kill 会话
ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost "tmux kill-session -t comfyui >/dev/null 2>&1" 2>$null
Start-Sleep -Seconds 2

if (Test-RemoteListening) {
    Write-Host "    仍在监听：非 tmux 管理的裸进程，按 main.py 命令行停止..." -ForegroundColor Yellow
    ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost "pkill -f 'python.*main.py.*--port ${RemotePort}'" 2>$null
    Start-Sleep -Seconds 3
    if (Test-RemoteListening) {
        Write-Host "    ❌ 远程进程仍在监听 ${RemotePort}，请手动检查 spark。" -ForegroundColor Red
    }
    else {
        Write-Host "    ✅ 远程 ComfyUI 裸进程已停止。" -ForegroundColor Green
    }
}
else {
    Write-Host "    ✅ 远程 ${RemotePort} 已无监听（幂等完成）。" -ForegroundColor Green
}

Write-Host "👋 清理完成。" -ForegroundColor Cyan
