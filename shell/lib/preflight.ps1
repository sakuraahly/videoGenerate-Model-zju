# ============================================================================
# shell/lib/preflight.ps1 — 前置检查库
# 供统一入口 / run_scheduled / check_environment / generate_video 复用：
#   1) 本地依赖与项目文件检查
#   2) 远程主机连通性
#   3) 远程模型清单检查（config/minimax_h3_models.json）
#   4) 缺失模型的自动下载（curl -C - 断点续传 + 重试）
# 依赖：utils.ps1 的 Write-Info / Write-Warn / Read-EnvConfig
# ============================================================================

# ---------------------------------------------------------------------------
# 1) 本地依赖与项目文件
# ---------------------------------------------------------------------------
function Test-LocalToolExists {
    param([string]$Name)
    return ($null -ne (Get-Command $Name -ErrorAction SilentlyContinue))
}

function Assert-PreflightBasics {
    <#
    .SYNOPSIS 检查本地工具 + 项目文件布局；打印缺失项。
    .PARAMETER SkipPromptChecks 使用指定工作流生成时跳过“参数/提示词”必须存在的检查。
    .RETURNS 全部通过返回 $true；否则 $false（不 exit，由调用方决定）。
    #>
    param([string]$ProjectRoot, [switch]$SkipPromptChecks)
    $ok = $true

    foreach ($tool in @('python', 'ssh', 'scp')) {
        if (-not (Test-LocalToolExists -Name $tool)) {
            Write-Warn "缺少本地命令 '$tool'（请安装并加入 PATH）。"
            $ok = $false
        }
    }

    $required = @{
        '参数文件'      = Join-Path $ProjectRoot 'parameters\video.txt'
        '正向提示词'    = Join-Path $ProjectRoot 'prompts\positive_prompts.txt'
        '提交脚本'      = Join-Path $ProjectRoot 'runs\h3_submit.py'
        'Python 包'     = Join-Path $ProjectRoot 'runs\h3\__init__.py'
        '环境配置'      = Join-Path $ProjectRoot 'config\environment.json'
        '模型清单'      = Join-Path $ProjectRoot 'config\minimax_h3_models.json'
        '生成脚本'      = Join-Path $ProjectRoot 'shell\generate_video.ps1'
    }
    if ($SkipPromptChecks) {
        $required.Remove('参数文件') | Out-Null
        $required.Remove('正向提示词') | Out-Null
    }
    foreach ($name in ($required.Keys | Sort-Object)) {
        if (-not (Test-Path -LiteralPath $required[$name])) {
            Write-Warn "缺少文件: $name -> $($required[$name])"
            $ok = $false
        }
    }
    if (-not $SkipPromptChecks) {
        $negative = Join-Path $ProjectRoot 'prompts\negative_prompts.txt'
        if (-not (Test-Path -LiteralPath $negative)) {
            Write-Warn "缺少负向提示词文件（可选，将按空负向处理）: $negative"
        }
    }

    $outputDir = Join-Path $ProjectRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    return $ok
}

# ---------------------------------------------------------------------------
# 2) 远程连通性（ComfyUI 进程状态见 remote.ps1，避免函数重名）
# ---------------------------------------------------------------------------
function Test-RemoteReachable {
    param([string]$RemoteHost, [int]$TimeoutSec = 12)
    ssh -o BatchMode=yes -o ConnectTimeout=$TimeoutSec $RemoteHost 'echo reachable-ok' 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------------------
# 3) 远程模型清单
# ---------------------------------------------------------------------------
function Get-ModelManifest {
    param([string]$ProjectRoot)
    $path = Join-Path $ProjectRoot 'config\minimax_h3_models.json'
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Warn "缺少模型清单文件: $path"
        return $null
    }
    try {
        $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        return $data   # 含 .prefix 与 .files
    }
    catch {
        Write-Warn "模型清单解析失败（$path）：$($_.Exception.Message)"
        return $null
    }
}

function Get-RemoteModelStatus {
    <#
    .SYNOPSIS 通过一次 ssh 调用统计 4 个模型文件的远程大小（字节）。
    .RETURNS 对象数组：{ Name, Target, RepoPath, Sha256, ApproxBytes,
                         RemoteBytes, Exists, Ok }；RemoteBytes=0 表示缺失。
    #>
    param([string]$RemoteHost, [string]$ModelsRoot, [object]$Manifest,
          [int]$TimeoutSec = 30)
    if (-not $Manifest -or -not $Manifest.files) { return @() }

    $segments = foreach ($f in $Manifest.files) {
        $filePath = "$ModelsRoot/$($f.target)/$($f.repo_path.Split('/')[-1])"
        # 说明：为避免 Windows 参数引号问题，整条远程命令不含双引号。
        # `$ 是 PowerShell 转义，bash 侧得到 $(...) 与 $s。
        "p=$filePath; s=`$(stat -c %s `$p 2>/dev/null); if [ -n `$s ]; then echo `$s; else echo 0; fi"
    }
    $remoteCmd = $segments -join '; '
    $out = ssh -o BatchMode=yes -o ConnectTimeout=$TimeoutSec $RemoteHost $remoteCmd 2>$null

    $result = @()
    $idx = 0
    foreach ($line in @($out)) {
        if ($idx -ge $Manifest.files.Count) { break }
        $f = $Manifest.files[$idx]
        $idx++
        $bytes = 0
        $trimmed = ([string]$line).Trim()
        if ($trimmed -match '^\d+$') { $bytes = [int64]$trimmed }
        $approx = [int64]([double]$f.approx_gb * 1GB)
        $ok = ($bytes -ge [int64]($approx * 0.85))
        $result += [pscustomobject]@{
            Name        = $f.repo_path.Split('/')[-1]
            RepoPath    = [string]$f.repo_path
            Target      = [string]$f.target
            Sha256      = [string]$f.sha256
            ApproxBytes = $approx
            RemoteBytes = $bytes
            Exists      = ($bytes -gt 0)
            Ok          = $ok
        }
    }
    # 输出行不足（ssh 异常/中断）时，剩余项按缺失处理
    while ($idx -lt $Manifest.files.Count) {
        $f = $Manifest.files[$idx]
        $idx++
        $approx = [int64]([double]$f.approx_gb * 1GB)
        $result += [pscustomobject]@{
            Name = $f.repo_path.Split('/')[-1]; RepoPath = [string]$f.repo_path
            Target = [string]$f.target; Sha256 = [string]$f.sha256
            ApproxBytes = $approx; RemoteBytes = [int64]0; Exists = $false; Ok = $false
        }
    }
    return $result
}

function Show-ModelStatus {
    <#
    .SYNOPSIS 打印模型状态表；返回 @{ Missing = 缺失列表; Down = 建议下载(缺失)列表 }。
    #>
    param([string]$RemoteHost, [object]$StatusList, [object]$Manifest)
    if (-not $StatusList) { return @{ Missing = @() } }
    $missing = @()
    Write-Info "远程模型检查（主机 $RemoteHost ，期望大小 = 清单 approx_gb）："
    foreach ($m in $StatusList) {
        $gb = if ($m.RemoteBytes -gt 0) { [math]::Round($m.RemoteBytes / 1GB, 2) } else { 0 }
        $state = if ($m.Ok) { 'OK' } elseif ($m.Exists) { '损坏/不完整' } else { '缺失' }
        $flag = if ($m.Ok) { '[OK]' } else { '[!!]' }
        Write-Host ("  {0,-5} {1,-58} 期望 {2,6:N2} GB / 远程 {3,6:N2} GB" -f `
            $flag, $m.Name, ([math]::Round($m.ApproxBytes / 1GB, 2)), $gb)
        if (-not $m.Ok) {
            Write-Host ("        状态: $state")
            $missing += $m
        }
    }
    Write-Host ''
    if ($missing.Count -eq 0) {
        Write-Info '所有基础模型文件均已就位。'
    }
    return @{ Missing = $missing }
}

function Invoke-RemoteModelDownload {
    <#
    .SYNOPSIS 依次下载缺失模型（远程 curl -fL -C - 断点续传 + 重试）。
    #>
    param([string]$RemoteHost, [string]$ModelsRoot, [object]$Manifest,
          [object[]]$MissingList, [int]$AttemptsPerFile = 3)
    if (-not $MissingList -or $MissingList.Count -eq 0) { return $true }
    $allOk = $true
    foreach ($m in $MissingList) {
        $fileName = $m.Name
        $url = "$($Manifest.prefix)$($m.RepoPath)"
        $dir = "$ModelsRoot/$($m.Target)"
        $filePath = "$dir/$fileName"
        Write-Info "下载模型: $fileName"
        Write-Info "  目标: $filePath"
        Write-Info "  来源: $url"

        # 确保远程目录存在
        ssh -o BatchMode=yes $RemoteHost "mkdir -p '$dir'" 2>$null | Out-Null

        $done = $false
        for ($i = 1; $i -le $AttemptsPerFile -and -not $done; $i++) {
            Write-Info "  curl 下载（第 ${i}/${AttemptsPerFile} 次，支持断点续传）..."
            ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=30 `
                $RemoteHost "curl -fL --retry 5 --retry-delay 3 -C - -o '$filePath' '$url'" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                # 校验大小（≥期望 85%）
                $size = (ssh -o BatchMode=yes $RemoteHost "stat -c %s '$filePath' 2>/dev/null" 2>$null).Trim()
                $sizeOk = ($size -match '^\d+$') -and ([int64]$size -ge [int64]($m.ApproxBytes * 0.85))
                if ($sizeOk) {
                    Write-Info "  $fileName 下载完成（$([math]::Round([int64]$size / 1GB, 2)) GB）。"
                    $done = $true
                }
                else {
                    Write-Warn "  文件大小仍不达标（远程 $size 字节），重试..."
                }
            }
            else {
                Write-Warn "  curl 返回异常，稍后重试..."
                Start-Sleep -Seconds 3
            }
        }
        if (-not $done) { $allOk = $false }
    }
    return $allOk
}
