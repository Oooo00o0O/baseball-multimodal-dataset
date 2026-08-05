param(
    [string[]]$BundlePath = @(),
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
try {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [Console]::InputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
    $env:PYTHONUTF8 = "1"
}
catch {
}

$workbenchDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $workbenchDir ".runtime\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "尚未创建运行环境。请先双击 start_mlb_candidate_curation.bat 启动一次。"
}

if (-not $BundlePath -or $BundlePath.Count -eq 0) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "选择所有成员交回的团队结果包 ZIP"
    $dialog.Filter = "团队结果包 (*.zip)|*.zip"
    $dialog.Multiselect = $true
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "没有选择团队结果包。"
    }
    $BundlePath = $dialog.FileNames
}
foreach ($path in $BundlePath) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "结果包不存在：$path"
    }
}
if (-not $OutputDir) {
    $stamp = [DateTime]::Now.ToString("yyyyMMdd-HHmmss")
    $OutputDir = Join-Path $workbenchDir "merged_results\$stamp"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

$arguments = @(
    (Join-Path $workbenchDir "merge_team_bundles.py")
) + $BundlePath + @("--output-dir", $OutputDir)
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "团队结果合并失败。原始 ZIP 没有被修改。"
}
Write-Host "合并完成：$OutputDir"
Start-Process explorer.exe -ArgumentList $OutputDir
