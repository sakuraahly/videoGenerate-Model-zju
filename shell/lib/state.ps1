# ============================================================================
# shell/lib/state.ps1 — 断点状态读取/清理（last_job.json + 旧版纯文本兼容）
# 说明：last_job.json 由 Python 端写入（提交后写 prompt_id，成功后补 remote_path），
#       PowerShell 端只负责读取决策与成功下载后清理。
# ============================================================================

function Get-JobState {
    param([string]$ProjectRoot)
    $out = [ordered]@{ prompt_id = ''; remote_path = '' }

    $jsonPath = Join-Path $ProjectRoot 'last_job.json'
    if (Test-Path -LiteralPath $jsonPath) {
        try {
            $data = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
            if ($data.prompt_id) { $out.prompt_id = [string]$data.prompt_id }
            if ($data.remote_path) { $out.remote_path = [string]$data.remote_path }
            return $out
        }
        catch {
            Write-Warn "断点文件 $jsonPath 解析失败，按无断点处理（将重新提交）。"
            return $out
        }
    }

    # 兼容旧版纯文本断点文件（内容为一行 prompt_id）
    $legacy = Join-Path $ProjectRoot 'last_prompt_id.txt'
    if (Test-Path -LiteralPath $legacy) {
        try {
            $pidText = (Get-Content -LiteralPath $legacy -Raw -ErrorAction Stop).Trim()
            if ($pidText) { $out.prompt_id = $pidText }
        }
        catch { }
    }
    return $out
}

function Clear-JobState {
    param([string]$ProjectRoot)
    foreach ($name in @('last_job.json', 'last_prompt_id.txt')) {
        $p = Join-Path $ProjectRoot $name
        if (Test-Path -LiteralPath $p) {
            try { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue } catch { }
        }
    }
}
