[CmdletBinding()]
param(
    [string]$OtaBaseUrl = "",
    [string]$IdfPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FirmwareDir = Join-Path $RepoRoot "firmware\firmware"
$Verifier = Join-Path $RepoRoot "scripts\verify_firmware_artifact.py"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    if ($WorkingDirectory) {
        Push-Location $WorkingDirectory
    }
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Read-DotEnvValue {
    param([string]$Path, [string]$Name)

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)$") {
            $value = $Matches[1].Trim()
            if ($value.Length -ge 2) {
                $first = $value[0]
                $last = $value[$value.Length - 1]
                if (($first -eq '"' -and $last -eq '"') -or
                    ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            return $value
        }
    }
    return ""
}

function Get-FreeDrive {
    param([char[]]$Preferred)

    foreach ($letter in $Preferred) {
        $drive = "${letter}:"
        if (-not (Test-Path "${drive}\")) {
            return $drive
        }
    }
    throw "No free drive letter is available for a short build path"
}

if ([string]::IsNullOrWhiteSpace($OtaBaseUrl)) {
    $OtaBaseUrl = $env:XIAOZHI_PUBLIC_OTA_BASE_URL
}
if ([string]::IsNullOrWhiteSpace($OtaBaseUrl)) {
    $OtaBaseUrl = Read-DotEnvValue (Join-Path $RepoRoot ".env") `
        "XIAOZHI_PUBLIC_OTA_BASE_URL"
}
if ([string]::IsNullOrWhiteSpace($OtaBaseUrl)) {
    throw "XIAOZHI_PUBLIC_OTA_BASE_URL is required (environment, make variable, or .env)"
}

$OtaBaseUrl = $OtaBaseUrl.Trim().TrimEnd("/")
$otaUri = $null
if (-not [Uri]::TryCreate($OtaBaseUrl, [UriKind]::Absolute, [ref]$otaUri) -or
    $otaUri.Scheme -notin @("http", "https") -or
    [string]::IsNullOrWhiteSpace($otaUri.Host) -or
    $otaUri.AbsolutePath -ne "/" -or
    $otaUri.Query -or $otaUri.Fragment -or $otaUri.UserInfo) {
    throw "XIAOZHI_PUBLIC_OTA_BASE_URL must be an HTTP(S) origin without a path"
}
$ExpectedOtaUrl = "$OtaBaseUrl/xiaozhi/ota/"

$environmentReady = (
    $env:IDF_PYTHON_ENV_PATH -and
    (Get-Command cmake.exe -ErrorAction SilentlyContinue) -and
    (Get-Command ninja.exe -ErrorAction SilentlyContinue)
)
if (-not $environmentReady) {
    $profiles = @(
        @(
            (Get-ChildItem `
                -Path (Join-Path $RepoRoot "tmp\eim-state") `
                -Filter "Microsoft.v5.5.4.PowerShell_profile.ps1" `
                -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1),
            (Get-Item "C:\Espressif\tools\Microsoft.v5.5.4.PowerShell_profile.ps1" `
                -ErrorAction SilentlyContinue)
        ) | Where-Object { $_ }
    )
    if ($profiles.Count -gt 0) {
        Set-StrictMode -Off
        . $profiles[0].FullName
        Set-StrictMode -Version Latest
    }
}

if ([string]::IsNullOrWhiteSpace($IdfPath)) {
    $IdfPath = $env:IDF_PATH
}
if ([string]::IsNullOrWhiteSpace($IdfPath)) {
    throw "ESP-IDF is not active. Run this target from an ESP-IDF 5.5.4 PowerShell"
}

$IdfPath = (Resolve-Path -LiteralPath $IdfPath).Path
$IdfPy = Join-Path $IdfPath "tools\idf.py"
if (-not (Test-Path -LiteralPath $IdfPy)) {
    throw "idf.py was not found under IDF_PATH: $IdfPath"
}

$PythonExe = ""
if ($env:IDF_PYTHON_ENV_PATH) {
    $candidate = Join-Path $env:IDF_PYTHON_ENV_PATH "Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate) {
        $PythonExe = $candidate
    }
}
if (-not $PythonExe) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $PythonExe = $pythonCommand.Source
    }
}
if (-not $PythonExe) {
    throw "The ESP-IDF Python environment is not available"
}

$cmakeSource = Get-Content -Raw -LiteralPath (Join-Path $FirmwareDir "CMakeLists.txt")
if ($cmakeSource -notmatch 'set\(PROJECT_VER\s+"([0-9]+\.[0-9]+\.[0-9]+)"\)') {
    throw "Could not read PROJECT_VER from firmware CMakeLists.txt"
}
$ProjectVersion = $Matches[1]

Write-Host "Building firmware $ProjectVersion without changing PROJECT_VER"
Write-Host "Embedding Dotty OTA endpoint: $ExpectedOtaUrl"

$env:XIAOZHI_PUBLIC_OTA_BASE_URL = $OtaBaseUrl
Invoke-Native $PythonExe @("fetch_repos.py") $FirmwareDir

$ProjectDrive = Get-FreeDrive @('P', 'Q', 'R')
$IdfDrive = Get-FreeDrive @('I', 'J', 'K')
try {
    Invoke-Native "subst.exe" @($ProjectDrive, $FirmwareDir)
    Invoke-Native "subst.exe" @($IdfDrive, $IdfPath)

    $env:IDF_PATH = "$IdfDrive\"
    $ShortIdfPy = "$IdfDrive\tools\idf.py"
    Invoke-Native $PythonExe @($ShortIdfPy, "reconfigure") "$ProjectDrive\"
    Invoke-Native $PythonExe @($ShortIdfPy, "build") "$ProjectDrive\"
}
finally {
    & subst.exe $IdfDrive /D 2>$null
    & subst.exe $ProjectDrive /D 2>$null
}

$BuildDir = Join-Path $FirmwareDir "build"
Invoke-Native $PythonExe @(
    $Verifier,
    "--binary", (Join-Path $BuildDir "stack-chan.bin"),
    "--project-description", (Join-Path $BuildDir "project_description.json"),
    "--expected-ota-url", $ExpectedOtaUrl
)

$Artifacts = @(
    "stack-chan.bin",
    "ota_data_initial.bin",
    "generated_assets.bin"
)
$ChecksumLines = foreach ($artifact in $Artifacts) {
    $path = Join-Path $BuildDir $artifact
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    "$hash  $artifact"
}
$ChecksumPath = Join-Path $BuildDir "SHA256SUMS.txt"
[IO.File]::WriteAllLines(
    $ChecksumPath,
    $ChecksumLines,
    [Text.UTF8Encoding]::new($false)
)
$ChecksumLines | ForEach-Object { Write-Host $_ }
Write-Host "Windows firmware build complete: $BuildDir"
