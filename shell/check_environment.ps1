<#
.SYNOPSIS
    环境与远程模型检查（统一入口选项 [5] 调用）。
    检查：本地依赖/文件、ssh spark 连通性、远程 ComfyUI 进程、
    4 个基础模型文件是否就位（config/minimax_h3_models.json）。
    若发现缺失，可交互选择立即自动下载（远程 curl 断点续传）。

.PARAMETER AutoDownload
    发现缺失时不再询问，直接自动下载。
#>
param([switch]$AutoDownload)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # shell\
$ProjectRoot = Split-Path -Parent $here
. (Join-Path $here 'lib\utils.ps1')
. (Join-Path $here 'lib\preflight.ps1')
. (Join-Path $here 'lib\remote.ps1')   # 提供 Test/Start-RemoteComfyUI

$envCfg = Read-EnvConfig -Path (Join-Path $ProjectRoot 'config\environment.json')
$RemoteHost = [string]$envCfg.remote_host
$ComfyUIPort = [int]$envCfg.comfyui_port
$RemoteComfyUIDir = [string]$envCfg.remote_comfyui_dir
$RemotePython = [string]$envCfg.remote_python
$TmuxSession = [string]$envCfg.tmux_session
$SshConnectTimeout = [Math]::Min(30, [Math]::Max(5, [int]$envCfg.ssh_connect_timeout_seconds))
$HealthTimeoutSeconds = [Math]::Max(30, [int]$envCfg.comfyui_health_timeout_seconds)
$ModelsRoot = "$RemoteComfyUIDir/models"

Write-Info '================ 环境与远程模型检查 ================'
Write-Host ''

# 1) 本地依赖与文件
Write-Info '[1/4] 本地依赖与项目文件...'
$localOk = Assert-PreflightBasics -ProjectRoot $ProjectRoot
Write-Host ''

# 2) 远程连通性
Write-Info "[2/4] 远程主机连通性 ($RemoteHost)..."
$remoteOk = Test-RemoteReachable -RemoteHost $RemoteHost
if ($remoteOk) { Write-Info '  远程主机可达（ssh ok）。' }
else { Write-Warn '  远程主机不可达！请检查网络与 ssh 免密配置。' }
Write-Host ''

# 3) 远程 ComfyUI 进程
$comfyOk = $false
if ($remoteOk) {
    Write-Info '[3/4] 远程 ComfyUI 进程状态...'
    $comfyOk = Test-RemoteComfyUI
    if ($comfyOk) { Write-Info '  ComfyUI 进程在运行。' }
    else { Write-Warn "  ComfyUI 未运行（生成时会自动通过 tmux 启动，端口 ${ComfyUIPort}）。" }
    Write-Host ''
}

# 4) 远程模型清单
Write-Info '[4/4] 远程基础模型文件检查...'
$manifest = Get-ModelManifest -ProjectRoot $ProjectRoot
$missing = @()
if ($remoteOk -and $manifest) {
    $status = Get-RemoteModelStatus -RemoteHost $RemoteHost -ModelsRoot $ModelsRoot -Manifest $manifest
    $report = Show-ModelStatus -RemoteHost $RemoteHost -StatusList $status -Manifest $manifest
    $missing = @($report.Missing)
}
elseif (-not $remoteOk) {
    Write-Warn '  跳过模型检查（远程不可达）。'
}
Write-Host ''

# 汇总
$allOk = $localOk -and $remoteOk -and ($missing.Count -eq 0)
Write-Info '================ 检查汇总 ================'
Write-Host ("  本地依赖/文件 : {0}" -f $(if ($localOk) { '通过' } else { '未通过' }))
Write-Host ("  远程主机       : {0}" -f $(if ($remoteOk) { '可达' } else { '不可达' }))
Write-Host ("  缺失模型数     : {0}" -f $missing.Count)
Write-Host ''

# 缺失模型 → 询问是否下载
if ($missing.Count -gt 0 -and $remoteOk) {
    $answer = ''
    if ($AutoDownload) { $answer = 'Y' }
    else {
        $answer = Read-Host '发现缺失/损坏的模型文件，是否立即自动下载？（Y=下载，回车=跳过）'
    }
    if ($answer -match '^[Yy]') {
        $ok = Invoke-RemoteModelDownload -RemoteHost $RemoteHost -ModelsRoot $ModelsRoot `
            -Manifest $manifest -MissingList $missing
        if ($ok) { Write-Info '模型补齐完成！' } else { Write-Warn '仍有模型未能下载成功，请检查网络后重试。' }
        $allOk = $allOk -and $ok
    }
}

if ($allOk) {
    Write-Info '环境检查通过，可以开始生成。'
    exit 0
}
else {
    Write-Warn '环境检查未完全通过，请根据上方提示处理。'
    exit 1
}
