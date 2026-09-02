<#
.SYNOPSIS
    流水线/多工作流 设置控制台（由 pipeline_setup.bat 启动）。
    管理 config/pipeline.json 的默认生成阶段，并检查各阶段模板就位情况。

功能：
  1) 查看全部阶段与模板状态
  2) 设置“默认生成阶段”（决定 run.bat / 菜单“立即生成”走哪种工作流）
  3) 校验某个阶段能否运行（调用 python h3_submit.py --stage X --dry-run）
  0) 返回
#>
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path          # shell\
$ProjectRoot = Split-Path -Parent $here
. (Join-Path $here 'lib\utils.ps1')

$PipelineFile = Join-Path $ProjectRoot 'config\pipeline.json'

function Read-Pipeline {
    $cfg = $null
    if (Test-Path -LiteralPath $PipelineFile) {
        try { $cfg = Get-Content -LiteralPath $PipelineFile -Raw | ConvertFrom-Json }
        catch { }
    }
    if (-not $cfg) {
        $cfg = [pscustomobject]@{ default_stage = 't2v'; templates_dir = 'config/templates'; stages = @{} }
        $cfg.stages = @{}
    }
    return $cfg
}

function Get-StageRows {
    param($Cfg)
    $rows = @()
    $tdir = Join-Path $ProjectRoot ([string]$Cfg.templates_dir)
    foreach ($prop in $Cfg.stages.PSObject.Properties) {
        $s = $Cfg.stages.($prop.Name)
        $tName = [string]$s.template
        $tPath = if ($tName) { Join-Path $tdir $tName } else { '' }
        $status = '内置'
        if ($tName) {
            if (Test-Path -LiteralPath $tPath) { $status = '模板就绪' } else { $status = '模板缺失' }
        }
        if ([string]$s.template_kind -eq 'ui') { $status += '(UI,CLI不可用)' }
        $rows += [pscustomobject]@{
            Id          = $prop.Name
            Description = [string]$s.description
            Kind        = [string]$s.kind
            Builtin     = [string]$s.builtin
            Template    = $tName
            Status      = $status
        }
    }
    return $rows
}

function Show-StageTable {
    $cfg = Read-Pipeline
    Write-Info "默认生成阶段: $($cfg.default_stage)   (模板目录: $($cfg.templates_dir))"
    Write-Host ''
    Write-Info '已注册阶段：'
    foreach ($r in (Get-StageRows -Cfg $cfg)) {
        Write-Host ("  [{0}] {1}" -f $r.Id, $r.Description)
        Write-Host ("       kind={0} builtin={1} template={2} 状态: {3}" -f `
            $r.Kind, $(if ($r.Builtin) { $r.Builtin } else { '-' }), `
            $(if ($r.Template) { $r.Template } else { '-' }), $r.Status)
    }
    return $cfg
}

function Ask-SetDefault {
    $cfg = Show-StageTable
    Write-Host ''
    $ids = @($cfg.stages.PSObject.Properties.Name)
    Write-Host '请输入要设为默认的阶段 id（可用: ' + ($ids -join ' / ') + '），回车取消：'
    $sel = (Read-Host '默认阶段').Trim()
    if (-not $sel) { return }
    if ($sel -notin $ids) { Write-Warn "未知阶段 '$sel'"; return }
    $cfg.default_stage = $sel
    $cfg | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $PipelineFile -Encoding UTF8
    Write-Info "已设置默认生成阶段 = $sel（run.bat / 菜单“立即生成”将按此阶段运行）。"
}

function Invoke-StageCheck {
    $cfg = Show-StageTable
    Write-Host ''
    $sel = (Read-Host '请输入要校验的阶段 id（回车取消）').Trim()
    if (-not $sel) { return }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { Write-Warn '未找到 python，无法校验。'; return }
    Write-Info "正在校验阶段 '$sel'（dry-run，不提交、不上传）..."
    & python "$(Join-Path $ProjectRoot 'runs\h3_submit.py')" --stage $sel --prompt '校验用提示词 placeholder' --dry-run 2>&1 | Select-Object -First 12
    Write-Host ("  退出码: " + $LASTEXITCODE)
}

Write-Host ''
Write-Host ('配置文件: ' + $PipelineFile) -ForegroundColor DarkGray
while ($true) {
    Write-Host ''
    Write-Host '  ============================================================'
    Write-Host '      流水线 / 多工作流 设置' -ForegroundColor Cyan
    Write-Host '  ============================================================'
    Write-Host '   [1] 查看全部阶段与模板状态'
    Write-Host '   [2] 设置默认生成阶段'
    Write-Host '   [3] 校验某个阶段（dry-run）'
    Write-Host '   [4] 手动编辑配置文件说明'
    Write-Host '   [0] 返回'
    Write-Host ''
    $choice = (Read-Host '请选择 (0-4)').Trim()
    switch ($choice) {
        '1' { $null = Show-StageTable }
        '2' { Ask-SetDefault }
        '3' { Invoke-StageCheck }
        '4' {
            Write-Host ''
            Write-Info "用文本编辑器打开 $PipelineFile 即可调整阶段/模板/默认图；模板文件放在 config/templates 目录。占位符见 docs/robustness-and-modularity.md。"
        }
        '0' { Write-Host ''; Write-Info '再见！'; return }
        default { Write-Warn "无效选择：'$choice'" }
    }
    Write-Host ''
    $null = Read-Host '按回车返回'
}
