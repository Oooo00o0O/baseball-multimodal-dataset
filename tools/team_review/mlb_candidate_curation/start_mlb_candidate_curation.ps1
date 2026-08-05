param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8767,
    [string]$BatchId = "",
    [string]$StartDate = "",
    [string]$EndDate = "",
    [string]$DataRoot = "",
    [ValidateRange(1, 500)]
    [int]$BufferTarget = 30,
    [ValidateRange(1, 20)]
    [int]$PerGameCap = 2,
    [ValidateRange(0, 100000)]
    [int]$CandidateLimit = 0,
    [switch]$RefreshDiscovery,
    [switch]$SkipDiscovery,
    [switch]$SkipPreparation,
    [switch]$PrepareOnly,
    [switch]$NoBrowser
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
    # Older PowerShell hosts may not expose mutable console encoding.
}

$workbenchDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $workbenchDir "..\..\.."))
$requirements = Join-Path $workbenchDir "requirements.txt"
$runtimeRoot = Join-Path $workbenchDir ".runtime"
$venvRoot = Join-Path $runtimeRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$localSettingsPath = Join-Path $workbenchDir "settings.local.json"

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

function Find-BasePython {
    $candidates = @()
    if ($env:MLB_CANDIDATE_CURATION_PYTHON) {
        $candidates += [PSCustomObject]@{
            Executable = $env:MLB_CANDIDATE_CURATION_PYTHON
            Prefix = @()
        }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += [PSCustomObject]@{
            Executable = $py.Source
            Prefix = @("-3")
        }
    }
    foreach ($name in @("python", "python3")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $candidates += [PSCustomObject]@{
                Executable = $command.Source
                Prefix = @()
            }
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Executable $candidate.Executable -PrefixArguments $candidate.Prefix) {
            return $candidate
        }
    }
    return $null
}

function Test-IsoDate {
    param([string]$Value)
    $parsed = [DateTime]::MinValue
    return [DateTime]::TryParseExact(
        $Value,
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsed
    )
}

function Resolve-FfmpegTool {
    param([string]$Name)
    if ($env:MLB_CANDIDATE_CURATION_FFMPEG_DIR) {
        $candidate = Join-Path $env:MLB_CANDIDATE_CURATION_FFMPEG_DIR "$Name.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    return $(if ($command) { $command.Source } else { "" })
}

if (Test-Path -LiteralPath $localSettingsPath -PathType Leaf) {
    try {
        $settings = Get-Content -LiteralPath $localSettingsPath -Raw | ConvertFrom-Json
        if (-not $DataRoot -and $settings.data_root) { $DataRoot = $settings.data_root }
        if (-not $BatchId -and $settings.batch_id) { $BatchId = $settings.batch_id }
        if (-not $StartDate -and $settings.start_date) { $StartDate = $settings.start_date }
        if (-not $EndDate -and $settings.end_date) { $EndDate = $settings.end_date }
    }
    catch {
        throw "本地设置文件无法读取：$localSettingsPath`n$($_.Exception.Message)"
    }
}

if (-not $DataRoot) {
    $DataRoot = Join-Path $projectRoot "data\review\mlb_candidate_curation"
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$inventory = Join-Path $DataRoot "candidate_inventory.csv"
$auxiliary = Join-Path $DataRoot "prefiltered_auxiliary_events.csv"
$mediaExclusions = Join-Path $DataRoot "prefiltered_media_exclusions.csv"
$cacheDir = Join-Path $DataRoot "cache"
$mediaRoot = Join-Path $DataRoot "media"
$reviewsDir = Join-Path $DataRoot "reviews"
$sessionPath = Join-Path $DataRoot "batch_session.json"
$newInventory = -not (Test-Path -LiteralPath $inventory -PathType Leaf)

if (Test-Path -LiteralPath $sessionPath -PathType Leaf) {
    try {
        $session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
        if (-not $BatchId -and $session.batch_id) { $BatchId = $session.batch_id }
        if (-not $StartDate -and $session.start_date) { $StartDate = $session.start_date }
        if (-not $EndDate -and $session.end_date) { $EndDate = $session.end_date }
    }
    catch {
        throw "批次记录无法读取：$sessionPath`n$($_.Exception.Message)"
    }
}

if (-not $BatchId) {
    $BatchId = Read-Host "请输入本批次代号（例如 member01_2025）"
}
if ($BatchId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
    throw "批次代号只能包含英文字母、数字、点、下划线和短横线，最长 64 位。"
}
if ($newInventory -and -not $SkipDiscovery) {
    if (-not $StartDate) { $StartDate = Read-Host "请输入负责日期段的开始日期（YYYY-MM-DD）" }
    if (-not $EndDate) { $EndDate = Read-Host "请输入负责日期段的结束日期（YYYY-MM-DD）" }
}
if (($StartDate -and -not (Test-IsoDate $StartDate)) -or ($EndDate -and -not (Test-IsoDate $EndDate))) {
    throw "日期必须采用 YYYY-MM-DD 格式。"
}
if (($StartDate -and -not $EndDate) -or ($EndDate -and -not $StartDate)) {
    throw "开始日期和结束日期必须同时填写。"
}
if ($StartDate -and $EndDate -and $EndDate -lt $StartDate) {
    throw "结束日期不能早于开始日期。"
}

$basePython = Find-BasePython
if (-not $basePython) {
    throw @"
未找到 Python 3.10 或更高版本。
请从 https://www.python.org/downloads/windows/ 安装 Python，并勾选 Add Python to PATH。
Microsoft Store 的 WindowsApps 占位符不算可用 Python。
"@
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "首次运行：正在创建 MLB 筛选台的独立 Python 环境……"
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    & $basePython.Executable @($basePython.Prefix) -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "创建独立 Python 环境失败。" }
}
& $venvPython -c "import numpy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "首次运行：正在安装音频分析依赖……"
    & $venvPython -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "依赖安装失败，请检查网络后重新双击启动。"
    }
}

$ffmpeg = Resolve-FfmpegTool "ffmpeg"
$ffprobe = Resolve-FfmpegTool "ffprobe"
if (-not $ffmpeg -or -not $ffprobe) {
    throw @"
未找到 FFmpeg 或 ffprobe，因此暂时不能下载后提取音频。
可在 PowerShell 运行：winget install Gyan.FFmpeg
安装完成后关闭本窗口并重新双击启动。
如果已经安装，也可把 MLB_CANDIDATE_CURATION_FFMPEG_DIR 设置为其 bin 目录。
"@
}

New-Item -ItemType Directory -Path $DataRoot,$reviewsDir -Force | Out-Null

$shouldDiscover = -not $SkipDiscovery -and $StartDate -and $EndDate -and ($newInventory -or $RefreshDiscovery)
if ($shouldDiscover) {
    Write-Host "正在读取 MLB 官方事件并建立候选清单：$StartDate 至 $EndDate"
    $discoverArguments = @(
        (Join-Path $workbenchDir "discover_mlb_candidates.py"),
        "--start-date", $StartDate,
        "--end-date", $EndDate,
        "--inventory", $inventory,
        "--auxiliary", $auxiliary,
        "--media-exclusions", $mediaExclusions,
        "--cache-dir", $cacheDir
    )
    if ($CandidateLimit -gt 0) { $discoverArguments += @("--limit", $CandidateLimit) }
    & $venvPython @discoverArguments
    if ($LASTEXITCODE -ne 0) { throw "候选发现失败；已保存的缓存不会丢失，可直接重试。" }
}
elseif ($newInventory -and -not $SkipDiscovery) {
    throw "首次运行必须填写日期段，才能建立候选清单。"
}

if (-not $SkipPreparation) {
    Write-Host "正在补充本地审核队列（目标 $BufferTarget 条）……"
    & $venvPython (Join-Path $workbenchDir "prepare_mlb_candidates.py") `
        --inventory $inventory `
        --reviews-dir $reviewsDir `
        --media-root $mediaRoot `
        --buffer-target $BufferTarget `
        --per-game-cap $PerGameCap `
        --ffmpeg $ffmpeg `
        --ffprobe $ffprobe
    if ($LASTEXITCODE -ne 0) { throw "媒体准备失败；已完成的文件会保留，可直接重试。" }
}

$sessionPayload = [ordered]@{
    batch_id = $BatchId
    start_date = $StartDate
    end_date = $EndDate
    data_root = $DataRoot
    updated_at = [DateTime]::UtcNow.ToString("o")
}
$sessionTemporary = "$sessionPath.tmp"
$sessionPayload | ConvertTo-Json | Set-Content -LiteralPath $sessionTemporary -Encoding UTF8
Move-Item -LiteralPath $sessionTemporary -Destination $sessionPath -Force

if ($PrepareOnly) {
    Write-Host "候选清单和本地审核队列已经准备完成。"
    exit 0
}

$reviews = Join-Path $reviewsDir "$BatchId.csv"
$serverArguments = @(
    (Join-Path $workbenchDir "server.py"),
    "--port", $Port,
    "--batch-id", $BatchId,
    "--inventory", $inventory,
    "--reviews", $reviews
)
if ($StartDate) { $serverArguments += @("--start-date", $StartDate) }
if ($EndDate) { $serverArguments += @("--end-date", $EndDate) }
if ($NoBrowser) { $serverArguments += "--no-browser" }

Write-Host "批次：$BatchId"
Write-Host "日期段：$(if ($StartDate) { "$StartDate 至 $EndDate" } else { "旧数据（未记录）" })"
Write-Host "本地数据：$DataRoot"
Write-Host "关闭本窗口会停止服务；再次双击会补充队列并继续。"
Push-Location $projectRoot
try {
    & $venvPython @serverArguments
    if ($LASTEXITCODE -ne 0) {
        throw "MLB 候选筛选台退出，错误码 $LASTEXITCODE。"
    }
}
finally {
    Pop-Location
}
