<#
.SYNOPSIS
    工作流上传与“使用指定工作流”设置（中文交互控制台）。
    由 workflow_setup.bat 启动；也可直接 powershell -File 运行。

功能：
  1) 设置 spark 上的绝对上传目录（scp 上传目标）
  2) 选择本地某个已保存工作流，让生成程序直接使用它（替代提示词方式）
  3) 手动把某个本地工作流立即上传到远程目录
  4) 查看/开关/清除当前设置
#>
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # shell\
$ProjectRoot = Split-Path -Parent $here
. (Join-Path $here 'lib\utils.ps1')
. (Join-Path $here 'lib\transfer.ps1')
. (Join-Path $here 'lib\preflight.ps1')

$envCfg = Read-EnvConfig -Path (Join-Path $ProjectRoot 'config\environment.json')
$RemoteHost = [string]$envCfg.remote_host

function Pause-Back {
    Write-Host ''
    $null = Read-Host '按回车返回'
}

function Read-ConfirmYes {
    $ans = (Read-Host '请确认 (Y/N)').Trim()
    return ($ans -match '^[Yy]$')
}

function Show-Settings {
    $cfg = Read-TransferConfig -ProjectRoot $ProjectRoot
    Write-Host ''
    Write-Info '-------- 当前设置 --------'
    Write-Host ("  远程上传目录     : " + $(if ($cfg.remote_upload_dir) { $cfg.remote_upload_dir } else { '（未设置）' }))
    Write-Host ("  激活工作流       : " + $(if ($cfg.active_workflow_dir) { $cfg.active_workflow_dir } else { '（未选择）' }))
    Write-Host ("  生成时使用工作流 : " + $(if ($cfg.use_active_workflow) { '开启' } else { '关闭' }))
    Write-Host '--------------------------'
    return $cfg
}

function Choose-FromWorkflowList {
    <# 交互选择一个本地工作流目录名；返回名称或空串（取消）。 #>
    param([object]$Candidates)
    if (-not $Candidates -or $Candidates.Count -eq 0) {
        Write-Warn '本地 workflows 下还没有任何已保存的工作流（先运行一次生成）。'
        return ''
    }
    Write-Host ''
    Write-Host '可用的本地工作流（最新在前）：'
    for ($i = 0; $i -lt $Candidates.Count; $i++) {
        $c = $Candidates[$i]
        $mark = if ($c.IsActive) { ' <== 当前激活' } else { '' }
        $flags = ''
        if ($c.ApiExists) { $flags += ' [api]' }
        if ($c.UiExists)  { $flags += ' [ui]' }
        Write-Host ("  [{0}] {1}{2}{3}" -f ($i + 1), $c.Name, $flags, $mark)
    }
    Write-Host "  [0] 取消"
    $sel = (Read-Host '请输入序号').Trim()
    if ($sel -eq '0' -or $sel -eq '') { return '' }
    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx) -or $idx -lt 1 -or $idx -gt $Candidates.Count) {
        Write-Warn "无效序号：'$sel'"
        return ''
    }
    return $Candidates[$idx - 1].Name
}

function Ask-SetRemoteDir {
    $cfg = Show-Settings
    Write-Host ''
    Write-Info '请输入 spark 上的绝对上传目录（必须以 / 开头，请勿使用 ~，可先 ssh 建好）：'
    if ($cfg.remote_upload_dir) { Write-Host ("  当前值: $($cfg.remote_upload_dir)  （直接回车保持不变）") }
    $new = (Read-Host '新目录').Trim()
    if ($new -eq '' -and $cfg.remote_upload_dir) { return }
    if ($new -eq '') { return }
    if (-not (Test-AbsoluteRemotePath -Path $new)) {
        Write-Warn "不是合法的绝对路径（应以 / 开头）：'$new'"
        return
    }
    $cfg.remote_upload_dir = $new
    Save-TransferConfig -ProjectRoot $ProjectRoot -Config $cfg
    Write-Info '已保存远程上传目录。'
}

function Ask-SelectActive {
    $cfg = Show-Settings
    $cands = @(Get-WorkflowCandidates -ProjectRoot $ProjectRoot)
    $name = Choose-FromWorkflowList -Candidates $cands
    if (-not $name) { return }
    $cfg.active_workflow_dir = $name
    $use = Read-ConfirmYes '是否让“生成程序直接使用该工作流”（跳过提示词/参数）？'
    $cfg.use_active_workflow = $use
    Save-TransferConfig -ProjectRoot $ProjectRoot -Config $cfg
    Write-Info "已激活: $name（生成时使用 = $use）"
}

function Ask-UploadNow {
    $cfg = Show-Settings
    if (-not (Test-AbsoluteRemotePath -Path $cfg.remote_upload_dir)) {
        Write-Warn '请先设置远程上传目录（选项 1）。'
        return
    }
    $cands = @(Get-WorkflowCandidates -ProjectRoot $ProjectRoot)
    $name = Choose-FromWorkflowList -Candidates $cands
    if (-not $name) { return }
    $local = Join-Path (Join-Path $ProjectRoot 'workflows') $name
    if (Upload-WorkflowFolder -LocalFolder $local -RemoteHost $RemoteHost -RemoteBaseDir $cfg.remote_upload_dir) {
        Write-Info "上传完成：${RemoteHost}:$($cfg.remote_upload_dir.TrimEnd('/'))/$name"
    }
    else {
        Write-Warn '上传未全部成功，请检查远程连通/路径后重试。'
    }
}

function Ask-ManageSettings {
    $cfg = Show-Settings
    Write-Host ''
    Write-Host '   [a] 切换“生成时使用工作流”（开/关）'
    Write-Host '   [b] 清除激活工作流'
    Write-Host '   [c] 清除远程上传目录'
    Write-Host '   [回车] 返回'
    $sel = (Read-Host '请选择').Trim().ToLowerInvariant()
    switch ($sel) {
        'a' {
            $cfg.use_active_workflow = -not $cfg.use_active_workflow
            Save-TransferConfig -ProjectRoot $ProjectRoot -Config $cfg
            Write-Info "已切换：生成时使用工作流 = $($cfg.use_active_workflow)"
        }
        'b' {
            $cfg.active_workflow_dir = ''
            $cfg.use_active_workflow = $false
            Save-TransferConfig -ProjectRoot $ProjectRoot -Config $cfg
            Write-Info '已清除激活工作流（生成恢复为使用提示词方式）。'
        }
        'c' {
            $cfg.remote_upload_dir = ''
            Save-TransferConfig -ProjectRoot $ProjectRoot -Config $cfg
            Write-Info '已清除远程上传目录。'
        }
        default { return }
    }
}

# ------------------------------- 主循环 -------------------------------
Write-Host ''
Write-Host ('远程主机: ' + $RemoteHost) -ForegroundColor DarkGray
while ($true) {
    Write-Host ''
    Write-Host '  ============================================================'
    Write-Host '      工作流上传 / 使用设置' -ForegroundColor Cyan
    Write-Host '  ============================================================'
    Write-Host '   [1] 设置 spark 远程上传目录（绝对路径）'
    Write-Host '   [2] 选择生成用工作流（并开启/关闭“直接使用该工作流”）'
    Write-Host '   [3] 立即把某个本地工作流上传到远程目录（scp）'
    Write-Host '   [4] 查看 / 切换开关 / 清除设置'
    Write-Host '   [0] 返回'
    Write-Host ''
    $choice = (Read-Host '请选择 (0-4)').Trim()
    switch ($choice) {
        '1' { Ask-SetRemoteDir; Pause-Back }
        '2' { Ask-SelectActive; Pause-Back }
        '3' { Ask-UploadNow; Pause-Back }
        '4' { Ask-ManageSettings; Pause-Back }
        '0' { Write-Host ''; Write-Info '再见！'; return }
        default { Write-Warn "无效选择：'$choice'" }
    }
}
