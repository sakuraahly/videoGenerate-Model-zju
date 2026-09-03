#Requires -Version 5.1
<#
.SYNOPSIS
    启动远程 ComfyUI（spark tmux 会话）并建立本地 SSH 隧道，可选打开浏览器。
.DESCRIPTION
    1. 检查 spark 上 tmux 会话 comfyui：已存在则视为运行中；否则启动
       ~/ai/ComfyUI/main.py（--listen 127.0.0.1，仅 spark 本机可达）。
    2. 建立本地 $LocalPort -> spark:$RemotePort 的 SSH 隧道。
       隧道用 Start-Process 拉起 ssh -N（Windows OpenSSH 的 -f 后台化不可靠），
       建立后循环探测 /system_stats 确认可用；本地已有可用端点则直接复用。
    3. 非 -NoBrowser 时自动打开浏览器。
.EXAMPLE
    powershell -File .\Start-ComfyUI.ps1 -NoBrowser   # 只建隧道不弹浏览器
#>

param(
    [string]$RemoteHost = "spark",
    [int]$LocalPort = 8188,
    [int]$RemotePort = 8188,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

function Test-ComfyEndpoint {
    param([int]$Port)
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${Port}/system_stats" -TimeoutSec 3
        return $r.StatusCode -eq 200
    }
    catch { return $false }
}

Write-Host "[1/3] 检查/启动远程 ComfyUI (spark, 端口 $RemotePort)..." -ForegroundColor Cyan
# 优先按端口探测（ComfyUI 可能由 tmux 或裸进程运行，端口在即视为已运行）
$probe = ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost "ss -ltn 2>/dev/null | grep -q ':${RemotePort} ' && echo UP || echo DOWN" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    ❌ 无法连接 spark（ssh 失败）。" -ForegroundColor Red
    exit 1
}
if ($probe -match 'UP') {
    Write-Host "    ✅ spark 上 ${RemotePort} 已在监听，视为运行中（未重复启动）。" -ForegroundColor Green
}
else {
    Write-Host "    未检测到远程监听，尝试用 tmux 启动 ComfyUI..." -ForegroundColor Yellow
    $launchCmd = "tmux new-session -d -s comfyui 'cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py " +
                 "--listen 127.0.0.1 --port $RemotePort --disable-auto-launch --reserve-vram 12'"
    ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost $launchCmd 2>$null
    Write-Host "    等待远程 ComfyUI 监听 ${RemotePort}（最多 60s）..." -ForegroundColor Yellow
    $deadlineRemote = (Get-Date).AddSeconds(60)
    $remoteUp = $false
    while ((Get-Date) -lt $deadlineRemote) {
        Start-Sleep -Seconds 3
        $probe2 = ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost "ss -ltn 2>/dev/null | grep -q ':${RemotePort} ' && echo UP || echo DOWN" 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe2 -match 'UP') { $remoteUp = $true; break }
    }
    if ($remoteUp) {
        Write-Host "    ✅ 远程 ComfyUI 已启动 (tmux: comfyui)。" -ForegroundColor Green
    }
    else {
        Write-Host "    ❌ 远程启动未生效（60s 内未监听）。请手动检查:" -ForegroundColor Red
        Write-Host "       ssh $RemoteHost `"tmux ls`"   /   `"~/ai/venv/bin/python ~/ai/ComfyUI/main.py --listen 127.0.0.1 --port $RemotePort`""
        exit 1
    }
}

Write-Host "[2/3] 建立本地 SSH 隧道 (localhost:${LocalPort} -> ${RemoteHost}:${RemotePort})..." -ForegroundColor Cyan
if (Test-ComfyEndpoint -Port $LocalPort) {
    Write-Host "    ✅ 本地端口 ${LocalPort} 已有可用 ComfyUI 端点，直接复用。" -ForegroundColor Green
}
else {
    # 端口被占但 HTTP 不通 = 死隧道/其它程序。是 ssh 则尝试清理后重建。
    $listener = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -ne 0 } |
        Select-Object -ExpandProperty OwningProcess -Unique
    $blocker = $null
    foreach ($procId in $listener) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq "ssh") { $blocker = $proc; break }
    }
    if ($blocker) {
        Write-Host "    本地 ${LocalPort} 被 ssh 进程占用但端点不可用（死隧道 PID $($blocker.Id)），尝试清理..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $blocker.Id -Force -ErrorAction Stop
            Start-Sleep -Milliseconds 800
            Write-Host "    ✅ 已清理死隧道进程。" -ForegroundColor Green
        }
        catch {
            Write-Host "    ❌ 无法清理占用 ${LocalPort} 的 ssh 进程 (PID $($blocker.Id)，可能权限不足)。" -ForegroundColor Red
            Write-Host "       请用管理员 PowerShell 执行: taskkill /PID $($blocker.Id) /F，然后重试本脚本。" -ForegroundColor Red
            exit 1
        }
    }
    elseif ($listener) {
        Write-Host "    ❌ 本地端口 ${LocalPort} 被其他进程占用且不是可用 ComfyUI（PID: $($listener -join ', ')）。" -ForegroundColor Red
        Write-Host "      请释放端口或改用其它 LocalPort 后重试。" -ForegroundColor Red
        exit 1
    }
    Write-Host "    启动 ssh -N 隧道进程..." -ForegroundColor Yellow
    $sshArgs = @('-N', '-L', "${LocalPort}:127.0.0.1:${RemotePort}",
                 '-o', 'ExitOnForwardFailure=yes',
                 '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4',
                 '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', $RemoteHost)
    $proc = Start-Process -FilePath 'ssh' -ArgumentList $sshArgs -PassThru -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(25)
    $tunnelOk = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 800
        if (Test-ComfyEndpoint -Port $LocalPort) { $tunnelOk = $true; break }
        if ($proc.HasExited) { break }
    }
    if ($tunnelOk) {
        Write-Host "    ✅ SSH 隧道就绪 (PID $($proc.Id))。" -ForegroundColor Green
    }
    else {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
        Write-Host "    ❌ SSH 隧道建立失败（25s 内未探活到 ComfyUI）。" -ForegroundColor Red
        Write-Host "      请确认 spark 上 ComfyUI 已监听 127.0.0.1:${RemotePort}。" -ForegroundColor Red
        exit 1
    }
}

if (-not $NoBrowser) {
    Write-Host "[3/3] 打开浏览器..." -ForegroundColor Cyan
    Start-Process "http://localhost:${LocalPort}"
}
else {
    Write-Host "[3/3] 跳过打开浏览器 (-NoBrowser)。" -ForegroundColor DarkGray
}

Write-Host "`n🚀 ComfyUI 已就绪！" -ForegroundColor Green
Write-Host "   访问地址: http://localhost:${LocalPort}"
Write-Host "   查看远程日志: ssh $RemoteHost `"tmux attach -t comfyui`"" -ForegroundColor Gray
