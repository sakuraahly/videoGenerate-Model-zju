<#
.SYNOPSIS
    一键生成 MiniMax H3 视频（模块化编排入口，Windows PowerShell 5.1+）

.DESCRIPTION
    本文件只做“编排”，具体能力分散在模块中，便于单独演进/测试：
      shell/lib/utils.ps1   日志、键值/JSON 读取、端口与端点探活、单实例锁
      shell/lib/state.ps1   断点状态（last_job.json）读取与清理
      shell/lib/remote.ps1  远程 ComfyUI 检查/启动
      shell/lib/tunnel.ps1  SSH 隧道生命周期（复用/自动换端口/崩溃自愈）
      runs/h3_submit.py     提交/轮询/输出定位（Python 侧模块化）
      config/environment.json  环境级单一配置（PS 与 Py 共享）

    断点重连：
      - 任务提交后 prompt_id 写入项目根 last_job.json（Python 维护）
      - 成功定位输出后还会补写 remote_path —— 下次可直接下载、免重复轮询
      - 隧道断开自动重建；下载失败保留断点，重跑 run.bat 自动续传
    资源保护：
      - 单实例锁：防止误双击多个 run.bat 同时提交任务
      - 本地端口被占用时自动换端口；仅清理自己启动的隧道进程
#>

$ErrorActionPreference = 'Continue'   # 不做全局 Stop，避免被无关小错误中断

# ------------------------------- 加载模块库 -------------------------------
$libFiles = @('utils.ps1', 'state.ps1', 'remote.ps1', 'tunnel.ps1', 'preflight.ps1', 'transfer.ps1')
foreach ($name in $libFiles) {
    $lib = Join-Path $PSScriptRoot ('lib\' + $name)
    if (-not (Test-Path -LiteralPath $lib)) {
        Write-Host "[ERROR] 缺少库文件: $lib"
        exit 1
    }
    . $lib
}

# ------------------------------- 项目路径 ---------------------------------
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ParametersFile    = Join-Path $ProjectRoot 'parameters\video.txt'
$PositivePromptFile = Join-Path $ProjectRoot 'prompts\positive_prompts.txt'
$NegativePromptFile = Join-Path $ProjectRoot 'prompts\negative_prompts.txt'
$SubmitScript       = Join-Path $ProjectRoot 'runs\h3_submit.py'
$OutputDir          = Join-Path $ProjectRoot 'outputs'
$LockPath           = Join-Path $ProjectRoot '.run.lock'
$TunnelRecordFile   = Join-Path $ProjectRoot '.tunnel.json'

# 读取 config/pipeline.json 的默认阶段（决定 run.bat/菜单[1-3] 走“经典提示词”还是“组合工作流”）
$DefaultStage = 't2v'
try {
    $pj = Get-Content -LiteralPath (Join-Path $ProjectRoot 'config\pipeline.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($pj -and $pj.default_stage) { $DefaultStage = [string]$pj.default_stage }
}
catch { }

# ------------------------------- 环境配置 ---------------------------------
$envCfg = Read-EnvConfig -Path (Join-Path $ProjectRoot 'config\environment.json')
$RemoteHost          = [string]$envCfg.remote_host
$ComfyUIPort         = [int]$envCfg.comfyui_port
$RemoteComfyUIDir    = [string]$envCfg.remote_comfyui_dir
$RemotePython        = [string]$envCfg.remote_python
$TmuxSession         = [string]$envCfg.tmux_session
$LocalPort           = [int]$envCfg.local_port
$PythonExe           = [string]$envCfg.python_exe
$SshConnectTimeout   = [Math]::Min(30, [Math]::Max(5, [int]$envCfg.ssh_connect_timeout_seconds))
$AliveInterval       = [int]$envCfg.server_alive_interval_seconds
$AliveCountMax       = [int]$envCfg.server_alive_count_max
$HealthTimeoutSeconds = [Math]::Max(30, [int]$envCfg.comfyui_health_timeout_seconds)
$MaxAttempts         = [Math]::Max(1, [int]$envCfg.max_attempts)
$RetryDelaySeconds   = [Math]::Max(1, [int]$envCfg.retry_delay_seconds)
$ScpAttempts         = [Math]::Max(1, [int]$envCfg.scp_attempts)

Set-TunnelContext -BasePort $LocalPort -RecordFile $TunnelRecordFile `
    -StartupWaitSeconds 8 -ConnectTimeout $SshConnectTimeout `
    -AliveIntervalSeconds $AliveInterval -AliveCountMax $AliveCountMax

# ------------------------------- 辅助函数 ---------------------------------
function Download-RemoteVideo {
    param([string]$RemotePath, [string]$LocalPath, [switch]$LocalCopy)
    for ($i = 1; $i -le $ScpAttempts; $i++) {
        if ($LocalCopy) {
            # 部署形态 spark-local：产物与仓库同机，直接复制（展开 ~ 为本机主目录）
            $src = $RemotePath -replace '^~', $HOME
            Copy-Item -LiteralPath $src -Destination $LocalPath -Force -ErrorAction SilentlyContinue
            $copyOk = (Test-Path -LiteralPath $LocalPath)
        }
        else {
            scp "${RemoteHost}:${RemotePath}" $LocalPath 2>$null
            $copyOk = ($LASTEXITCODE -eq 0)
        }
        if ($copyOk -and (Test-Path -LiteralPath $LocalPath)) {
            $size = (Get-Item -LiteralPath $LocalPath).Length
            if ($size -gt 0) {
                Write-Info "下载成功（$size 字节）。"
                return $true
            }
            Write-Warn '取到的文件为空，清理后重试...'
            Remove-Item -LiteralPath $LocalPath -Force -ErrorAction SilentlyContinue
        }
        else {
            Write-Warn "产物拉取失败（第 ${i}/${ScpAttempts} 次，方式: $(if ($LocalCopy) { '本机复制' } else { 'scp' })）。"
        }
        if ($i -lt $ScpAttempts) { Start-Sleep -Seconds $RetryDelaySeconds }
    }
    return $false
}

function Get-OutputMarker {
    param($Output, [string]$Pattern)
    if (-not $Output) { return '' }
    $m = $Output | Select-String -Pattern $Pattern
    if ($m) { return $m[0].Matches[0].Groups[1].Value.Trim() }
    return ''
}

function Invoke-H3Submit {
    param([string[]]$ArgsList)
    try {
        $output = & $PythonExe @ArgsList 2>&1
        $code = $LASTEXITCODE
    }
    catch {
        Write-Warn "无法调用 Python（$PythonExe）：$($_.Exception.Message)"
        return @{ ExitCode = 9001; Output = @() }
    }
    return @{ ExitCode = $code; Output = $output }
}

# =============================== 主流程 ====================================
# 0) 运行日志：logs\run_<时间戳>.log（同时供 Python 端经 H3_LOG_FILE 追加）
$runLog = Initialize-RunLog -ProjectRoot $ProjectRoot
$env:H3_LOG_FILE = $runLog
Write-Host "[INFO] 运行日志: $runLog"

# 0b) 部署形态：win-remote（默认，Windows + ssh 隧道） | spark-local（整体在 spark，同机直连）
$DeploySite = 'win-remote'
$DeployFetch = 'scp'
try {
    $dp = Get-Content -LiteralPath (Join-Path $ProjectRoot 'config\deploy.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($dp -and $dp.site -in @('win-remote', 'spark-local')) { $DeploySite = [string]$dp.site }
    $sprops = $dp.sites.($DeploySite)
    if ($sprops -and $sprops.fetch) { $DeployFetch = [string]$sprops.fetch }
}
catch { }

Write-Info '=============================================='
Write-Info ' MiniMax H3 视频生成（断点可恢复版）'
if ($DeploySite -eq 'spark-local') {
    Write-Info " 部署形态: spark-local（同机直连 ComfyUI/模型，无需隧道）"
}
else {
    Write-Info " 部署形态: win-remote  远程主机: $RemoteHost  本地隧道端口: $LocalPort"
}
Write-Info '=============================================='

# 0) 工作流传输/使用配置（workflow_setup.bat 维护）
$transferCfg = Read-TransferConfig -ProjectRoot $ProjectRoot
$useWorkflowFile = $false
$activeWorkflowApi = ''
if ($transferCfg.use_active_workflow -and $transferCfg.active_workflow_dir) {
    $candidateApi = Join-Path $ProjectRoot ($transferCfg.active_workflow_dir + '\workflow_api.json')
    if (Test-Path -LiteralPath $candidateApi) {
        $useWorkflowFile = $true
        $activeWorkflowApi = $candidateApi
        Write-Info "已启用“使用指定工作流”: $($transferCfg.active_workflow_dir)"
    }
    else {
        Write-Warn "transfer.json 指向的激活工作流不存在（$candidateApi），本次回退为提示词方式。请运行 workflow_setup.bat 重新选择或关闭该模式。"
    }
}

# 1) 前置检查（快速失败）——逻辑收敛到 shell/lib/preflight.ps1，多处复用
if (-not (Assert-PreflightBasics -ProjectRoot $ProjectRoot -SkipPromptChecks:$useWorkflowFile)) {
    Write-ErrorExit '前置检查未通过。可在“统一控制台”选择 [5] 查看详细环境报告并修复。'
}

# 当前参数提示（仅展示；真正解析以 Python 端为准，避免逻辑重复；工作流模式无参数文件需求）
if ($useWorkflowFile) {
    Write-Info '运行模式：指定工作流原样提交（跳过提示词/参数）'
}
elseif ($DefaultStage -eq 't2v') {
    Write-Info "运行模式：经典提示词（内置 T2V；正向/负向文件 + parameters\video.txt）"
}
else {
    Write-Info "运行模式：组合工作流 --stage $DefaultStage（提示词用 prompts\workflows\<该模板槽位>）"
}
$params = Read-KeyValueFile -Path $ParametersFile
if (-not $useWorkflowFile) {
    if ($params['resolution']) { Write-Info "当前参数: 分辨率=$($params['resolution'])" }
    if ($params['seconds'])    { Write-Info "当前参数: 时长=$($params['seconds']) 秒" }
}
else {
    Write-Info "本次生成使用指定工作流（跳过参数/提示词解析）。"
}

$lock = $null
try {
    # 1) 单实例运行锁
    $lock = New-ProjectLock -Path $LockPath

    # 2) 确保 ComfyUI 可访问（按部署形态：远程经隧道 / spark-local 同机直连）
    if ($DeploySite -eq 'spark-local') {
        Write-Info '部署形态 spark-local：检查本机 ComfyUI...'
        if (-not (Test-HttpEndpoint -Port $LocalPort)) {
            Write-ErrorExit '本机 ComfyUI 未运行（127.0.0.1:8188）。请先启动 ComfyUI 后重试（spark-local 不需要隧道）。'
        }
        $env:COMFYUI_URL = "http://127.0.0.1:${LocalPort}"
        Write-Info "ComfyUI 访问地址: $env:COMFYUI_URL（本机直连）"
    }
    else {
        # 3) 确保 SSH 隧道可用（复用/自愈/自动换端口）—— win-remote 形态
        Write-Info '检查远程 ComfyUI 状态...'
        if (Test-RemoteComfyUI) {
            Write-Info 'ComfyUI 已在运行。'
        }
        else {
            Start-RemoteComfyUI
        }
        if (-not (Ensure-Tunnel)) {
            Write-ErrorExit '无法建立可用的 SSH 隧道。请检查网络、远程主机与本地端口占用情况。'
        }
        # 让 Python 客户端使用实际本地端口（自动换端口时与默认不同）
        $env:COMFYUI_URL = "http://127.0.0.1:${LocalPortUsed}"
        Write-Info "ComfyUI 访问地址: $env:COMFYUI_URL"
    }

    # 4) 断点状态决策
    $state = Get-JobState -ProjectRoot $ProjectRoot
    $remoteVideoPath = $null

    if ($state.remote_path) {
        # 已定位远程视频但上次下载未完成 -> 跳过 Python，直接续传下载
        Write-Info "断点已包含远程视频路径，跳过轮询，直接下载: $($state.remote_path)"
        $remoteVideoPath = $state.remote_path
    }
    elseif ($state.prompt_id) {
        Write-Info "检测到断点任务 $($state.prompt_id)，将通过 Python 恢复该任务（不会重复生成）。"
    }

    # 5) Python 提交/轮询（可重试循环）
    $attempt = 0
    $script:WorkflowUploaded = $false   # 每次运行只上传一次本次保存的工作流
    while (-not $remoteVideoPath -and $attempt -lt $MaxAttempts) {
        $attempt++
        Write-Info "第 ${attempt}/${MaxAttempts} 次尝试..."

        # 每轮都确认隧道仍存活，断开则自动重建
        if (-not (Test-HttpEndpoint -Port $LocalPortUsed)) {
            Write-Warn '隧道已断开，正在重建...'
            if (-not (Ensure-Tunnel)) {
                Write-ErrorExit '无法重建 SSH 隧道，请检查网络后重新运行 run.bat（断点已保留）。'
            }
            $env:COMFYUI_URL = "http://127.0.0.1:${LocalPortUsed}"
        }

        $pythonArgs = @($SubmitScript)
        if ($state.prompt_id) {
            # 断点恢复：不再重新提交，直接轮询原任务
            $pythonArgs += @('--resume', $state.prompt_id)
        }
        elseif ($useWorkflowFile) {
            # “使用指定工作流”模式：直接提交选中的 API 工作流
            $pythonArgs += @('--workflow-file', $activeWorkflowApi)
        }
        elseif ($DefaultStage -eq 't2v') {
            # 经典提示词模式（默认阶段 t2v）：正向/负向提示词文件 + parameters\video.txt
            $pythonArgs += @('--prompt-file', $PositivePromptFile,
                             '--negative-prompt-file', $NegativePromptFile)
        }
        else {
            # 组合工作流模式：跑默认阶段的模板，提示词自动用该模板的槽位文件
            $pythonArgs += @('--stage', $DefaultStage)
        }

        $result = Invoke-H3Submit -ArgsList $pythonArgs
        if ($result.Output) {
            $result.Output | ForEach-Object { Write-Host "    $_" }
        }

        $marker = Get-OutputMarker -Output $result.Output -Pattern '^REMOTE_VIDEO_PATH:\s*(.+)$'

        # 本次动态构建的工作流已落盘 -> 按配置 scp 上传到 spark（仅一次，失败不阻断）
        $wfMarker = Get-OutputMarker -Output $result.Output -Pattern '^WORKFLOW_SAVED_DIR:\s*(.+)$'
        if ($wfMarker -and -not $script:WorkflowUploaded -and $transferCfg.remote_upload_dir) {
            $script:WorkflowUploaded = $true
            Write-Info "上传本次工作流到 ${RemoteHost}:$($transferCfg.remote_upload_dir) ..."
            if (-not (Upload-WorkflowFolder -LocalFolder $wfMarker -RemoteHost $RemoteHost `
                      -RemoteBaseDir $transferCfg.remote_upload_dir)) {
                Write-Warn '工作流上传失败（不影响视频生成；稍后可用 workflow_setup.bat [3] 手动上传）。'
            }
        }

        if ($result.ExitCode -eq 0 -and $marker) {
            $remoteVideoPath = $marker
        }
        elseif ($result.ExitCode -eq 3 -or $result.ExitCode -ge 90) {
            # Python 判定为确定性/内部错误：不再重试
            Write-ErrorExit "任务不可恢复（退出码 $($result.ExitCode)），已停止。请查看上方日志。"
        }
        else {
            Write-Warn "本次未成功（Python 退出码 $($result.ExitCode)）。"
            if ($attempt -lt $MaxAttempts) {
                Write-Info "将在 ${RetryDelaySeconds} 秒后自动重试..."
                Start-Sleep -Seconds $RetryDelaySeconds
            }
        }
    }

    if (-not $remoteVideoPath) {
        Write-ErrorExit "重试 ${MaxAttempts} 次仍未成功。断点已保留，网络恢复后重新运行 run.bat 即可自动续传。"
    }

    # 6) 下载到 outputs（文件名自动递增，不覆盖旧视频）
    $existing = Get-ChildItem -LiteralPath $OutputDir -Filter 'video_*.mp4' -ErrorAction SilentlyContinue
    $maxNum = 0
    foreach ($file in $existing) {
        if ($file.Name -match '^video_(\d+)\.mp4$') {
            $num = [int]$matches[1]
            if ($num -gt $maxNum) { $maxNum = $num }
        }
    }
    $localVideoPath = Join-Path $OutputDir ("video_" + ($maxNum + 1) + '.mp4')
    Write-Info "产物路径: $remoteVideoPath"
    Write-Info "保存到:   $localVideoPath"

    $dlArgs = @('-RemotePath', $remoteVideoPath, '-LocalPath', $localVideoPath)
    if ($DeployFetch -eq 'local_cp') { $dlArgs += '-LocalCopy' }
    if (-not (Download-RemoteVideo @dlArgs)) {
        Write-ErrorExit "产物拉取失败。断点已保留，重新运行 run.bat 将直接重试。"
    }

    # 7) 成功 -> 清理断点
    Clear-JobState -ProjectRoot $ProjectRoot
    Write-Info '全部完成！视频已保存，可自行打开播放。'
}
finally {
    if (Test-Path Env:COMFYUI_URL) { Remove-Item Env:COMFYUI_URL -ErrorAction SilentlyContinue }
    if (Test-Path Env:H3_LOG_FILE) { Remove-Item Env:H3_LOG_FILE -ErrorAction SilentlyContinue }
    if ($DeploySite -ne 'spark-local') { Stop-Tunnel }   # spark-local 无隧道
    Release-ProjectLock -Handle $lock -Path $LockPath
}
