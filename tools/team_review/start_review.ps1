param(
    [string]$AssignmentPath,
    [string]$ReviewerId,
    [string]$DatasetRoot,
    [string]$OutputRoot,
    [ValidateRange(1, 65535)]
    [int]$GroundPort = 8765,
    [ValidateRange(1, 65535)]
    [int]$FlyPort = 8766,
    [switch]$NoBrowser,
    [switch]$PrepareOnly
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
    # Older PowerShell hosts may not expose a mutable console encoding.
}
$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $toolRoot "..\.."))
$launcher = Join-Path $toolRoot "launcher.py"

function Select-AssignmentFile {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "选择审核任务 TXT（每行一个 sample ID）"
    $dialog.Filter = "TXT 任务清单 (*.txt)|*.txt|所有文件 (*.*)|*.*"
    $dialog.Multiselect = $false
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "未选择任务 TXT。"
    }
    return $dialog.FileName
}

function Select-DatasetFolder {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "选择 dataset 文件夹，或选择包含 dataset 文件夹的仓库根目录"
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "未选择数据目录。"
    }
    return $dialog.SelectedPath
}

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )
    if (-not $Executable -or $Executable -like "*\WindowsApps\python*.exe") {
        return $false
    }
    & $Executable @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

if (-not $AssignmentPath) {
    $AssignmentPath = Select-AssignmentFile
}
if (-not (Test-Path -LiteralPath $AssignmentPath -PathType Leaf)) {
    throw "任务 TXT 不存在：$AssignmentPath"
}
if (-not $ReviewerId) {
    $ReviewerId = Read-Host "请输入审核人代号（例如 member01）"
}
if (-not $ReviewerId) {
    throw "审核人代号不能为空。"
}

if (-not $DatasetRoot) {
    $defaultDataset = Join-Path $repositoryRoot "dataset"
    if (Test-Path -LiteralPath $defaultDataset -PathType Container) {
        $DatasetRoot = $defaultDataset
    }
    else {
        $DatasetRoot = Select-DatasetFolder
    }
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $toolRoot "review_outputs"
}

$pythonCandidates = @()
if ($env:TEAM_REVIEW_PYTHON) {
    $pythonCandidates += [PSCustomObject]@{
        Executable = $env:TEAM_REVIEW_PYTHON
        Prefix = @()
    }
}
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $pythonCandidates += [PSCustomObject]@{
        Executable = $pyLauncher.Source
        Prefix = @("-3")
    }
}
foreach ($commandName in @("python", "python3")) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($command) {
        $pythonCandidates += [PSCustomObject]@{
            Executable = $command.Source
            Prefix = @()
        }
    }
}

$python = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-PythonCandidate -Executable $candidate.Executable -PrefixArguments $candidate.Prefix) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    throw @"
未找到 Python 3.10 或更高版本。
请从 https://www.python.org/downloads/windows/ 安装 Python，并勾选 Add Python to PATH；
也可以把 TEAM_REVIEW_PYTHON 设置为 python.exe 的完整路径。
Microsoft Store 的 WindowsApps 占位符不算可用 Python。
"@
}

$arguments = @(
    $launcher,
    "--assignment", (Resolve-Path -LiteralPath $AssignmentPath).Path,
    "--reviewer", $ReviewerId,
    "--dataset-root", $DatasetRoot,
    "--output-root", $OutputRoot,
    "--ground-port", $GroundPort,
    "--fly-port", $FlyPort
)
if ($NoBrowser) {
    $arguments += "--no-browser"
}
if ($PrepareOnly) {
    $arguments += "--prepare-only"
}

Write-Host "使用 Python：$($python.Executable) $($python.Prefix -join ' ')"
Write-Host "任务 TXT：$AssignmentPath"
Write-Host "数据目录：$DatasetRoot"
& $python.Executable @($python.Prefix) @arguments
if ($LASTEXITCODE -ne 0) {
    throw "团队审核工具退出，错误码 $LASTEXITCODE。"
}
