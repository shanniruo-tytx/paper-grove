# Paper Grove - one-line bootstrap for a FRESH Windows machine.
#
# Usage (PowerShell, no need to install anything first):
#   irm https://raw.githubusercontent.com/shanniruo-tytx/paper-grove/main/scripts/bootstrap.ps1 | iex
#
# Or with options (save the file first, or use scriptblock):
#   & ([scriptblock]::Create((irm <url>))) -Dir D:\kb -Port 9000 -Background
#
# What it does:
#   1. find Python 3.8+ (install via winget if missing)
#   2. find Git (install via winget if missing)
#   3. clone the repo (or fast-forward update if already cloned)
#   4. run deploy.py  (deps -> categories.json -> build with 2 gates -> serve)
#
# NOTE: this file is intentionally ASCII-only so Windows PowerShell 5.1
# (which reads BOM-less .ps1 as ANSI/GBK) never garbles it.

param(
    [string]$Dir = (Join-Path $HOME "paper-grove"),
    [string]$Repo = "https://github.com/shanniruo-tytx/paper-grove.git",
    [string]$Branch = "main",
    [string]$Port = "8766",
    [string]$Bundle = "",          # optional: path or URL of a content zip (see scripts/bundle.py)
    [string]$Python = "",          # optional: explicit python.exe (when installed but not on PATH)
    [switch]$NoServe,
    [switch]$Background,
    [switch]$NoDeps
)

$ErrorActionPreference = "Stop"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Good($m) { Write-Host "    [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    [!]  $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "    [x]  $m" -ForegroundColor Red }

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machine + ";" + $user)
}

function Find-Python {
    $candidates = @(
        @{ exe = "python"; pre = @() },
        @{ exe = "py";     pre = @("-3") },
        @{ exe = "python3"; pre = @() }
    )
    foreach ($c in $candidates) {
        try {
            $out = & $c.exe @($c.pre + @("-c", "import sys;print(sys.version_info[0]*1000+sys.version_info[1])")) 2>$null
            if (-not $out) { continue }
            $ver = [int]($out | Select-Object -Last 1).ToString().Trim()
            if ($ver -ge 3008) {
                return @{ exe = $c.exe; pre = $c.pre; ver = $ver }
            }
        } catch { }
    }
    return $null
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Paper Grove - fresh machine bootstrap (Windows)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 1. Python ----------
Info "[1/4] Python 3.8+"
$py = $null
if ($Python -ne "") {
    if (-not (Test-Path $Python)) { Bad "-Python path not found: $Python"; exit 1 }
    $out = & $Python -c "import sys;print(sys.version_info[0]*1000+sys.version_info[1])" 2>$null
    $ver = if ($out) { [int]($out | Select-Object -Last 1).ToString().Trim() } else { 0 }
    if ($ver -lt 3008) { Bad "$Python is too old (need 3.8+)"; exit 1 }
    $py = @{ exe = $Python; pre = @(); ver = $ver }
    Good ("Using explicit python: " + $Python)
}
if ($null -eq $py) { $py = Find-Python }
if ($null -eq $py) {
    Warn "Python not found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing Python 3.12 via winget (may take a minute)..."
        & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        Refresh-Path
        $py = Find-Python
    } else {
        Bad "winget unavailable. Please install Python 3.8+ from https://www.python.org/downloads/"
        Bad "then re-run this command."
        exit 1
    }
}
if ($null -eq $py) {
    Bad "Python 3.8+ still not found after install. Open a NEW terminal and re-run."
    exit 1
}
Good ("Python found: " + $py.exe + " " + ($py.pre -join " "))

# ---------- 2. Git ----------
Info "[2/4] Git"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Warn "Git not found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing Git via winget..."
        & winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Bad "Git unavailable. Install it from https://git-scm.com/ then re-run."
    exit 1
}
Good "Git found"

# ---------- 3. Clone / update ----------
Info "[3/4] Source code -> $Dir"
$gitDir = Join-Path $Dir ".git"
if (Test-Path $gitDir) {
    Good "Existing repo detected, fast-forward update..."
    # git writes progress to stderr; keep it from becoming a terminating ErrorRecord
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $Dir
    (& git pull --ff-only 2>&1) | ForEach-Object { Write-Host "      $_" }
    $pullRc = $LASTEXITCODE
    Pop-Location
    $ErrorActionPreference = $oldEap
    if ($pullRc -ne 0) { Warn "git pull failed (local commits ahead?) - keeping local copy" }
} else {
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    (& git clone --branch $Branch $Repo $Dir 2>&1) | ForEach-Object { Write-Host "      $_" }
    $cloneRc = $LASTEXITCODE
    $ErrorActionPreference = $oldEap
    if ($cloneRc -ne 0) {
        Bad "git clone failed. Check network / repo URL: $Repo"
        exit 1
    }
    Good "Cloned."
}

# ---------- 3.5 Content bundle (optional) ----------
# content/** and categories.json are gitignored (personal data), so a fresh
# clone is an empty site. Pass -Bundle <zip|url> to restore your library.
if ($Bundle -ne "") {
    Info "[3.5/4] Importing content bundle"
    $zip = $Bundle
    if ($Bundle -match '^https?://') {
        $zip = Join-Path $env:TEMP ("pg-bundle-" + [System.IO.Path]::GetFileName($Bundle))
        Info "Downloading bundle ..."
        try {
            Invoke-WebRequest -Uri $Bundle -OutFile $zip -UseBasicParsing
        } catch {
            Bad "bundle download failed: $($_.Exception.Message)"
            exit 1
        }
    }
    if (-not (Test-Path $zip)) { Bad "bundle not found: $zip"; exit 1 }
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    (& $py.exe @($py.pre + @((Join-Path $Dir "scripts/bundle.py"), "import", $zip, "--root", $Dir)) 2>&1) | ForEach-Object { Write-Host "      $_" }
    $bundleRc = $LASTEXITCODE
    $ErrorActionPreference = $oldEap
    if ($bundleRc -ne 0) { Bad "bundle import failed"; exit 1 }
    Good "Content imported."
}

# ---------- 4. Deploy ----------
Info "[4/4] deploy.py"
Push-Location $Dir
$argsList = @() + $py.pre + @("deploy.py", "--port", $Port)
if ($NoServe)    { $argsList += "--no-serve" }
if ($Background) { $argsList += "--background" }
if ($NoDeps)     { $argsList += "--no-deps" }
& $py.exe @argsList
$rc = $LASTEXITCODE
Pop-Location

if ($rc -ne 0) {
    Bad "deploy.py exited with code $rc"
    exit $rc
}
