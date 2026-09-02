# ============================================================================
# shell/lib/tunnel.ps1 — SSH 隧道生命周期管理
# 特性：
#   * 若本地端口上已有可用的 ComfyUI 端点则直接复用（不重复建隧道）
#   * 记录自己启动的 ssh PID（.tunnel.json），崩溃后不会误杀别人的进程
#   * 本地端口被占用/转发失败时自动换用下一个空闲端口（上限 5 次尝试）
#   * 每次启动前先做 HTTP 探活，避免“端口通但隧道没通”的空转
# 依赖（脚本级变量）：$RemoteHost $ComfyUIPort
# ============================================================================

$script:LocalPortBase = 8188
$script:LocalPortUsed = 0
$script:TunnelRecordFile = ''
$script:TunnelStartupWaitSeconds = 8
$script:TunnelConnectTimeout = 10
$script:AliveInterval = 15
$script:AliveCountMax = 4

function Set-TunnelContext {
    param([int]$BasePort, [string]$RecordFile,
          [int]$StartupWaitSeconds = 8, [int]$ConnectTimeout = 10,
          [int]$AliveIntervalSeconds = 15, [int]$AliveCountMax = 4)
    $script:LocalPortBase = $BasePort
    $script:LocalPortUsed = 0
    $script:TunnelRecordFile = $RecordFile
    $script:TunnelStartupWaitSeconds = [Math]::Max(2, $StartupWaitSeconds)
    $script:TunnelConnectTimeout = [Math]::Min(15, [Math]::Max(3, $ConnectTimeout))
    $script:AliveInterval = $AliveIntervalSeconds
    $script:AliveCountMax = $AliveCountMax
}

function Read-TunnelRecord {
    if (-not $script:TunnelRecordFile -or -not (Test-Path -LiteralPath $script:TunnelRecordFile)) {
        return $null
    }
    try {
        return (Get-Content -LiteralPath $script:TunnelRecordFile -Raw | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

function Write-TunnelRecord {
    param([int]$Pid, [int]$Port)
    if (-not $script:TunnelRecordFile) { return }
    try {
        [ordered]@{ pid = $Pid; port = $Port; started_at = (Get-Date -Format 'o') } |
            ConvertTo-Json | Set-Content -LiteralPath $script:TunnelRecordFile -Encoding UTF8
    }
    catch { }
}

# 只清理“我们自己记录过”的隧道进程，避免误杀用户其他 ssh
function Stop-Tunnel {
    $rec = Read-TunnelRecord
    if ($rec -and $rec.pid) {
        $proc = Get-Process -Id ([int]$rec.pid) -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Info "清理上次的 SSH 隧道进程 (PID $($rec.pid))..."
            Stop-Process -Id ([int]$rec.pid) -Force -ErrorAction SilentlyContinue
        }
    }
    if ($script:TunnelRecordFile -and (Test-Path -LiteralPath $script:TunnelRecordFile)) {
        try { Remove-Item -LiteralPath $script:TunnelRecordFile -Force -ErrorAction SilentlyContinue } catch { }
    }
    $script:LocalPortUsed = 0
}

function Start-TunnelProc {
    param([int]$Port)
    $argsStr = "-N -L ${Port}:127.0.0.1:${ComfyUIPort} " +
               "-o ConnectTimeout=${script:TunnelConnectTimeout} " +
               "-o ServerAliveInterval=${script:AliveInterval} " +
               "-o ServerAliveCountMax=${script:AliveCountMax} " +
               "-o ExitOnForwardFailure=yes -o TCPKeepAlive=yes ${RemoteHost}"
    $proc = Start-Process -FilePath 'ssh' -ArgumentList $argsStr -PassThru -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds($script:TunnelStartupWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 1000
        if (Test-HttpEndpoint -Port $Port) {
            Write-TunnelRecord -Pid $proc.Id -Port $Port
            Write-Info "SSH 隧道就绪（本地端口 $Port，PID $($proc.Id)）"
            return $true
        }
        if ($proc.HasExited) {
            Write-Warn "ssh 隧道进程提前退出（退出码 $($proc.ExitCode)），端口 $Port。"
            break
        }
    }
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    return $false
}

# 确保本地有一条可用隧道；成功返回 true 并设置 $script:LocalPortUsed
function Ensure-Tunnel {
    # 1) 已有可用端点（含上次遗留/用户自建隧道）→ 直接复用
    if (Test-HttpEndpoint -Port $script:LocalPortBase) {
        $script:LocalPortUsed = $script:LocalPortBase
        Write-Info "检测到本地 ${script:LocalPortBase} 已有可用 ComfyUI 端点，直接复用。"
        return $true
    }
    # 2) 清理我们自己记录过的（可能已死）旧隧道
    Stop-Tunnel
    # 3) 在 base..base+19 中找空闲端口并尝试建立（最多启动 5 次）
    $tried = 0
    for ($port = $script:LocalPortBase; $port -lt ($script:LocalPortBase + 20); $port++) {
        if (Test-TcpPort -Port $port) { continue }   # 被其他程序占用
        $tried++
        Write-Info "尝试在本地端口 $port 建立 SSH 隧道..."
        if (Start-TunnelProc -Port $port) {
            $script:LocalPortUsed = $port
            return $true
        }
        if ($tried -ge 5) { break }
    }
    $script:LocalPortUsed = 0
    return $false
}
