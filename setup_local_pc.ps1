# =============================================================================
# ResearchFlow local setup (Windows PowerShell). Safe to run again at any time:
# it only installs what is missing or changed and never overwrites backend\.env.
# =============================================================================
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Find-Python {
    foreach ($cmd in @(@("py", "-3"), @("python"))) {
        try {
            $exe = $cmd[0]; $rest = @($cmd | Select-Object -Skip 1)
            $out = & $exe @rest -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -match "True") { return ,$cmd }
        } catch { }
    }
    return $null
}

Write-Host "== ResearchFlow setup ==" -ForegroundColor Cyan

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH')." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js was not found. Install the LTS version from https://nodejs.org/ and open a new window." -ForegroundColor Red
    exit 1
}

# --- Backend --------------------------------------------------------------
$venvPy = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating Python environment (backend\.venv)..." -ForegroundColor Yellow
    & $py[0] @($py | Select-Object -Skip 1) -m venv (Join-Path $root "backend\.venv")
}
$reqFile = Join-Path $root "backend\requirements.txt"
$reqStamp = Join-Path $root "backend\.venv\.requirements.sha256"
$reqHash = (Get-FileHash $reqFile -Algorithm SHA256).Hash
if (-not (Test-Path $reqStamp) -or (Get-Content $reqStamp) -ne $reqHash) {
    Write-Host "Installing backend packages..." -ForegroundColor Yellow
    & $venvPy -m pip install --disable-pip-version-check -q -r $reqFile
    if ($LASTEXITCODE -ne 0) { Write-Host "Backend package install failed." -ForegroundColor Red; exit 1 }
    Set-Content -Path $reqStamp -Value $reqHash
}

$envFile = Join-Path $root "backend\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "Creating backend\.env with fresh secrets (kept out of Git)..." -ForegroundColor Yellow
    $secret = { & $venvPy -c "import secrets; print(secrets.token_urlsafe(48))" }
    @(
        "# Local development settings. Git-ignored; never commit this file.",
        "APP_ENV=development",
        "FRONTEND_ORIGIN=http://localhost:5173",
        "DATABASE_PATH=./tmp/researchflow.sqlite3",
        "PRIVATE_STORAGE_DIR=./private_uploads",
        "MAX_UPLOAD_SIZE_BYTES=104857600",
        "PROJECT_STORAGE_QUOTA_BYTES=2147483648",
        "SESSION_SECRET_KEY=$(& $secret)",
        "CSRF_SECRET_KEY=$(& $secret)",
        "TOKEN_HASH_PEPPER=$(& $secret)"
    ) | Set-Content -Path $envFile -Encoding UTF8
}

# --- Frontend -------------------------------------------------------------
$lockFile = Join-Path $root "frontend\package-lock.json"
$lockStamp = Join-Path $root "frontend\node_modules\.package-lock.sha256"
$lockHash = (Get-FileHash $lockFile -Algorithm SHA256).Hash
if (-not (Test-Path $lockStamp) -or (Get-Content $lockStamp) -ne $lockHash) {
    Write-Host "Installing frontend packages..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "frontend")
    npm install --no-fund --no-audit
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Write-Host "Frontend package install failed." -ForegroundColor Red; exit 1 }
    Set-Content -Path $lockStamp -Value $lockHash
}

Write-Host "Setup complete." -ForegroundColor Green
