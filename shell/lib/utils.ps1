# ============================================================================
# shell/lib/utils.ps1 — 通用工具库（被 generate_video.ps1 dot-source 引入）
# 依赖注入：调用方需先定义 $script: 级变量后再调用；本文件函数不持有全局状态。
# ============================================================================

$script:RunLogPath = ''

function Write-FileLog {
    param([string]$Message)
    if (-not $script:RunLogPath) { return }
    try {
        Add-Content -LiteralPath $script:RunLogPath -Encoding UTF8 `
            -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
    }
    catch { }
}

function Initialize-RunLog {
    <#
    .SYNOPSIS 在项目根 logs\ 下创建 run_<时间戳>_<毫秒>.log 并记录起始行；返回日志路径。
    毫秒后缀与任务目录 h3_<时间戳>_<毫秒> 对齐，避免同秒多次运行撞名。
    #>
    param([string]$ProjectRoot)
    if ($script:RunLogPath) { return $script:RunLogPath }
    $dir = Join-Path $ProjectRoot 'logs'
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $script:RunLogPath = Join-Path $dir ('run_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '.log')
    Write-FileLog "=== MiniMax H3 run start $(Get-Date -Format o) ==="
    return $script:RunLogPath
}

function Get-RunLogPath { return $script:RunLogPath }

function Write-Info {
    param([string]$Message)
    Write-FileLog "[INFO] $Message"
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-FileLog "[WARN] $Message"
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrorExit {
    param([string]$Message)
    Write-FileLog "[ERROR] $Message"
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 读取 key=value 文本文件（兼容 BOM/CRLF/注释/大小写/行内空白）
# ---------------------------------------------------------------------------
function Read-KeyValueFile {
    param([string]$Path)
    $table = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $table }
    $lines = Get-Content -LiteralPath $Path -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $lines) { return $table }
    foreach ($line in $lines) {
        $t = [string]$line
        if ($null -eq $t) { continue }
        $t = $t.Trim()
        if (-not $t) { continue }
        if ($t.StartsWith('#') -or $t.StartsWith(';')) { continue }
        $idx = $t.IndexOf('=')
        if ($idx -le 0) { continue }            # 无等号的非法行，容错跳过
        $key = $t.Substring(0, $idx).Trim().ToLowerInvariant()
        $value = $t.Substring($idx + 1).Trim()
        if ($key) { $table[$key] = $value }
    }
    return $table
}

# ---------------------------------------------------------------------------
# 读取 config/environment.json；缺失/损坏时回退默认值（单点配置，跨 PS/Py 共享）
# ---------------------------------------------------------------------------
function Read-EnvConfig {
    param([string]$Path)
    $cfg = [ordered]@{
        remote_host                 = 'spark'
        remote_comfyui_dir          = '~/ai/ComfyUI'
        remote_python               = '~/ai/venv/bin/python'
        tmux_session                = 'comfyui'
        remote_output_dir           = '~/ai/ComfyUI/output'
        comfyui_port                = 8188
        local_port                  = 8188
        ssh_connect_timeout_seconds = 20
        server_alive_interval_seconds = 15
        server_alive_count_max      = 4
        comfyui_health_timeout_seconds = 90
        python_exe                  = 'python'
        max_attempts                = 3
        retry_delay_seconds         = 5
        scp_attempts                = 3
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn "未找到环境配置文件 $Path ，使用内置默认值。"
        return $cfg
    }
    try {
        $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        foreach ($prop in $data.PSObject.Properties) {
            $cfg[$prop.Name] = $prop.Value
        }
    }
    catch {
        Write-Warn "环境配置文件解析失败（$Path）：$($_.Exception.Message)，使用默认值。"
    }
    return $cfg
}

# ---------------------------------------------------------------------------
# 网络探活
# ---------------------------------------------------------------------------
function Test-TcpPort {
    param([int]$Port, [int]$TimeoutMs = 1500)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($ok) {
            $client.EndConnect($iar)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    }
    catch {
        return $false
    }
}

function Test-HttpEndpoint {
    param([int]$Port, [int]$TimeoutSec = 5)
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${Port}/system_stats" `
            -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        return ($resp.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

# ---------------------------------------------------------------------------
# 单实例运行锁：独占文件句柄，进程退出/崩溃时由 OS 自动释放，无需清理“僵尸锁”
# ---------------------------------------------------------------------------
function New-ProjectLock {
    param([string]$Path)
    try {
        return [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None)
    }
    catch {
        Write-ErrorExit "检测到另一个 run.bat / generate_video.ps1 正在运行（无法获得运行锁 $Path）。请先关闭正在运行的窗口再试。"
    }
}

function Release-ProjectLock {
    param($Handle, [string]$Path)
    if ($Handle) {
        try { $Handle.Dispose() } catch { }
    }
    if (Test-Path -LiteralPath $Path) {
        try { Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue } catch { }
    }
}
