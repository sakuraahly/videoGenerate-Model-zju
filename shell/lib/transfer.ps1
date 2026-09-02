# ============================================================================
# shell/lib/transfer.ps1 — 工作流上传 / 指定工作流 配置与操作
# 配置文件：config/transfer.json
#   remote_upload_dir    : spark 上绝对路径（以 / 开头），把本地保存的工作流 scp 过去
#   active_workflow_dir  : 本地 workflows 下某任务文件夹名（相对项目根）
#   use_active_workflow  : 生成时是否直接使用 active 工作流（跳过提示词/参数）
# ============================================================================

function Get-TransferConfigPath {
    param([string]$ProjectRoot)
    return (Join-Path $ProjectRoot 'config\transfer.json')
}

function Read-TransferConfig {
    param([string]$ProjectRoot)
    $out = [ordered]@{
        remote_upload_dir    = ''
        active_workflow_dir  = ''
        use_active_workflow  = $false
    }
    $path = Get-TransferConfigPath -ProjectRoot $ProjectRoot
    if (Test-Path -LiteralPath $path) {
        try {
            $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            if ($data.remote_upload_dir)   { $out.remote_upload_dir = [string]$data.remote_upload_dir }
            if ($data.active_workflow_dir) { $out.active_workflow_dir = [string]$data.active_workflow_dir }
            $out.use_active_workflow = [bool]($data.use_active_workflow -eq $true)
        }
        catch {
            Write-Warn "transfer.json 解析失败（$path）：$($_.Exception.Message)，按默认设置处理。"
        }
    }
    return $out
}

function Save-TransferConfig {
    param([string]$ProjectRoot, $Config)
    $path = Get-TransferConfigPath -ProjectRoot $ProjectRoot
    $dir = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $Config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $path -Encoding UTF8
}

function Test-AbsoluteRemotePath {
    param([string]$Path)
    $p = ([string]$Path).Trim()
    return ($p -match '^/' -and $p.Length -gt 1)
}

function Get-ActiveWorkflowApiPath {
    <#
    .SYNOPSIS 返回激活工作流的 workflow_api.json 绝对路径；未设置/不存在返回空串。
    #>
    param([string]$ProjectRoot)
    $cfg = Read-TransferConfig -ProjectRoot $ProjectRoot
    if (-not $cfg.active_workflow_dir) { return '' }
    $api = Join-Path $ProjectRoot ($cfg.active_workflow_dir + '\workflow_api.json')
    if (-not (Test-Path -LiteralPath $api)) { return '' }
    return $api
}

function Get-WorkflowCandidates {
    <#
    .SYNOPSIS 列出本地 workflows 下的任务目录（含是否含 api/ui、是否激活）。
    .RETURNS pscustomobject 数组：Name, ApiExists, UiExists, IsActive。
    #>
    param([string]$ProjectRoot)
    $cfg = Read-TransferConfig -ProjectRoot $ProjectRoot
    $root = Join-Path $ProjectRoot 'workflows'
    if (-not (Test-Path -LiteralPath $root)) { return @() }
    $out = @()
    foreach ($d in @(Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending)) {
        $out += [pscustomobject]@{
            Name     = $d.Name
            ApiExists = (Test-Path -LiteralPath (Join-Path $d.FullName 'workflow_api.json'))
            UiExists  = (Test-Path -LiteralPath (Join-Path $d.FullName 'workflow_ui.json'))
            IsActive  = ($d.Name -eq $cfg.active_workflow_dir)
        }
    }
    return $out
}

# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------
function Upload-WorkflowFolder {
    <#
    .SYNOPSIS 把本地任务文件夹里的 workflow_api.json / workflow_ui.json
              scp 上传到 spark:$RemoteBaseDir/<文件夹名>/（自动 mkdir -p）。
    .RETURNS $true 全部文件上传成功（或没有可传文件时视为失败并提示）。
    #>
    param([string]$LocalFolder, [string]$RemoteHost, [string]$RemoteBaseDir)
    if (-not (Test-Path -LiteralPath $LocalFolder)) {
        Write-Warn "本地工作流文件夹不存在: $LocalFolder"
        return $false
    }
    if (-not (Test-AbsoluteRemotePath -Path $RemoteBaseDir)) {
        Write-Warn "远程上传目录不是绝对路径（应以 / 开头）: '$RemoteBaseDir'"
        return $false
    }
    $folderName = Split-Path -Leaf $LocalFolder
    $remoteDir = $RemoteBaseDir.TrimEnd('/') + '/' + $folderName

    Write-Info "创建远程目录: ${RemoteHost}:$remoteDir"
    ssh -o BatchMode=yes -o ConnectTimeout=15 $RemoteHost "mkdir -p '$remoteDir'" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "远程 mkdir 失败（ssh 不可达或目录权限问题）。"
        return $false
    }

    $okAll = $true
    $any = $false
    foreach ($fileName in @('workflow_api.json', 'workflow_ui.json')) {
        $localFile = Join-Path $LocalFolder $fileName
        if (-not (Test-Path -LiteralPath $localFile)) { continue }
        $any = $true
        $remoteFile = $remoteDir + '/' + $fileName
        # 远程路径含空格时加单引号（远端 shell 展开）
        $remoteSpec = if ($remoteFile -match ' ') { "${RemoteHost}:'$remoteFile'" } else { "${RemoteHost}:${remoteFile}" }
        Write-Info "上传 $fileName -> ${RemoteHost}:${remoteFile}"
        scp -o BatchMode=yes -o ConnectTimeout=15 -q $localFile $remoteSpec 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "上传失败: $fileName"
            $okAll = $false
        }
    }
    if (-not $any) {
        Write-Warn '本地文件夹中没有 workflow_api.json / workflow_ui.json 可上传。'
        return $false
    }
    return $okAll
}
