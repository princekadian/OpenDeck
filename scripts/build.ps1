<#
Builds OpenDeck from source:  frontend -> tests -> OpenDeck.exe (PyInstaller) -> installer (Inno Setup).

    powershell -ExecutionPolicy Bypass -File scripts\build.ps1               # everything
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -SkipTests    # faster
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -NoInstaller  # dist\OpenDeck only

Needs (developer machine only): Python 3.12 (64-bit), Node.js 20+, Inno Setup 6 for the installer.
Output: dist\OpenDeck\OpenDeck.exe and dist\installer\OpenDeck-Setup-<version>.exe
See BUILD.md.
#>
param([switch]$SkipTests, [switch]$NoInstaller)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$exe $($arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

$version = (Select-String -Path backend\opendeck\__init__.py -Pattern '__version__ = "([^"]+)"').Matches.Groups[1].Value
Write-Host "OpenDeck $version"

Step "Python environment (.venv)"
if (-not (Test-Path .venv\Scripts\python.exe)) { Run py @("-3.12", "-m", "venv", ".venv") }
$py = Join-Path $root ".venv\Scripts\python.exe"
Run $py @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "backend\requirements-dev.txt", "-r", "backend\requirements-build.txt")

Step "Frontend"
Push-Location frontend
try {
    Run npm @("ci", "--no-audit", "--no-fund")
    Run npm @("run", "build")
    if (-not $SkipTests) { Run npm @("test") }
} finally { Pop-Location }

if (-not $SkipTests) {
    Step "Backend tests"
    Push-Location backend
    try { Run $py @("-m", "pytest", "-q") } finally { Pop-Location }
}

Step "Application (PyInstaller)"
Run $py @("-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", "--distpath", "dist", "--workpath", "build\pyinstaller", "packaging\OpenDeck.spec")
Write-Host "Built dist\OpenDeck\OpenDeck.exe"

if (-not $NoInstaller) {
    Step "Installer (Inno Setup)"
    $iscc = @(
        (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) or use -NoInstaller." }
    Run $iscc @("/Q", "/DAppVersion=$version", "installer\OpenDeck.iss")
    Write-Host "Built dist\installer\OpenDeck-Setup-$version.exe" -ForegroundColor Green
}
