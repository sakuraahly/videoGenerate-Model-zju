# DeployMode.ps1 — 运行形态切换（bats\config\mode.bat 启动）
# 形态 A（win-remote，默认/现状）：项目在 Windows，ssh 隧道连 spark ComfyUI/模型。
# 形态 B（spark-local，交付形态）：项目整体在 spark，同机直连 ComfyUI 与本地模型，无需隧道。
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $here
$Py = Join-Path $ProjectRoot 'runs\h3\deploy.py'
. (Join-Path $here 'lib\utils.ps1')

function Invoke-Py {
    param([string[]]$ArgsList)
    & python @ArgsList
    Write-Host ''
    Write-Host ("  退出码: " + $LASTEXITCODE)
}

while ($true) {
    Write-Host ''
    Write-Host '  ============================================================'
    Write-Host '      运行形态（部署模式）切换' -ForegroundColor Cyan
    Write-Host '  ============================================================'
    Write-Host '   [1] 查看当前形态'
    Write-Host '   [2] 切到 spark-local（整体部署在 spark：ComfyUI/模型同机直连）'
    Write-Host '   [3] 切到 win-remote（本地 Windows + 远程 spark，ssh 隧道）'
    Write-Host '   [0] 返回'
    Write-Host ''
    $choice = (Read-Host '请选择 (0-3)').Trim()
    switch ($choice) {
        '1' { Invoke-Py @('--show') }
        '2' { Invoke-Py @('--set', 'spark-local') }
        '3' { Invoke-Py @('--set', 'win-remote') }
        '0' { Write-Host ''; Write-Info '再见！'; return }
        default { Write-Warn "无效选择：'$choice'" }
    }
    Write-Host ''
    $null = Read-Host '按回车返回菜单'
}
