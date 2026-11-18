<#
.SYNOPSIS
  Builds everything the hall needs, on a machine WITH internet. Result: deploy\bundle\ (copy it to USB).

.DESCRIPTION
  bundle\
    neurotlon-images.tar   server and web images (docker save)
    SHA256SUMS.txt
    docker-compose.yml, .env.example, README.md
    scripts\               install-admin.ps1, make-certs.ps1
    tools\                 mkcert.exe (put it here beforehand: -MkcertExe path\to\mkcert.exe)
    stand\                 for the stand PCs (offline install):
      uv.exe, python\ (Python 3.12 for uv), uv-cache\ (all wheels), neurotlon\ (sources),
      install-stand.ps1

  Needs: Docker Desktop (running), uv. Run from anywhere:
    powershell -ExecutionPolicy Bypass -File deploy\scripts\build-bundle.ps1 -MkcertExe C:\tools\mkcert.exe

.PARAMETER SkipImages
  Do not build or save the Docker images (stand part only).
.PARAMETER SkipStand
  Do not prepare the stand part (images only).
#>
[CmdletBinding()]
param(
  [string]$OutDir,
  [string]$MkcertExe,
  [switch]$SkipImages,
  [switch]$SkipStand
)

$ErrorActionPreference = 'Stop'
$deployDir = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $deployDir
if (-not $OutDir) { $OutDir = Join-Path $deployDir 'bundle' }

function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Run([scriptblock]$cmd, [string]$what) {
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

# ---- common files ----------------------------------------------------------------------------
Step 'Copying compose files, scripts and the runbook'
Copy-Item (Join-Path $deployDir 'docker-compose.yml') $OutDir -Force
Copy-Item (Join-Path $deployDir '.env.example') $OutDir -Force
Copy-Item (Join-Path $deployDir 'README.md') $OutDir -Force
$scriptsOut = Join-Path $OutDir 'scripts'
New-Item -ItemType Directory -Force -Path $scriptsOut | Out-Null
foreach ($name in 'install-admin.ps1', 'make-certs.ps1') {
  Copy-Item (Join-Path $PSScriptRoot $name) $scriptsOut -Force
}
$toolsOut = Join-Path $OutDir 'tools'
New-Item -ItemType Directory -Force -Path $toolsOut | Out-Null
if ($MkcertExe) {
  Copy-Item $MkcertExe (Join-Path $toolsOut 'mkcert.exe') -Force
} elseif (-not (Test-Path (Join-Path $toolsOut 'mkcert.exe'))) {
  Write-Warning 'mkcert.exe is not in bundle\tools. Download it and put it there, or pass -MkcertExe.'
}

# ---- images ----------------------------------------------------------------------------------
if (-not $SkipImages) {
  Step 'Building Docker images'
  Run { docker info *> $null } 'docker info (is Docker Desktop running?)'
  Push-Location $deployDir
  try {
    Run { docker compose -f docker-compose.yml -f docker-compose.build.yml build } 'docker compose build'
  } finally { Pop-Location }

  Step 'Saving images to neurotlon-images.tar'
  $tar = Join-Path $OutDir 'neurotlon-images.tar'
  Run { docker save neurotlon-server:local neurotlon-web:local -o $tar } 'docker save'
  $hash = (Get-FileHash $tar -Algorithm SHA256).Hash.ToLower()
  # ASCII, one line "hash  name": the same format sha256sum uses.
  [IO.File]::WriteAllText((Join-Path $OutDir 'SHA256SUMS.txt'), "$hash  neurotlon-images.tar`n")
}

# ---- stand -----------------------------------------------------------------------------------
if (-not $SkipStand) {
  Step 'Preparing the stand bundle (sources, Python, wheel cache)'
  $uvCmd = Get-Command uv -ErrorAction Stop
  $stand = Join-Path $OutDir 'stand'
  if (Test-Path $stand) { Remove-Item -Recurse -Force $stand }
  New-Item -ItemType Directory -Force -Path $stand | Out-Null
  Copy-Item $uvCmd.Source (Join-Path $stand 'uv.exe')
  Copy-Item (Join-Path $PSScriptRoot 'install-stand.ps1') $stand

  # The lockfile describes the whole workspace, so the server's manifest and sources travel too
  # (a few files); its own dependencies are not installed on stands.
  $src = Join-Path $stand 'neurotlon'
  New-Item -ItemType Directory -Force -Path $src | Out-Null
  Copy-Item (Join-Path $repo 'pyproject.toml') $src
  Copy-Item (Join-Path $repo 'uv.lock') $src
  foreach ($dir in 'server', 'launcher', 'bci-bridge', 'games', 'shared') {
    robocopy (Join-Path $repo $dir) (Join-Path $src $dir) /E /NFL /NDL /NJH /NJS /NP `
      /XD __pycache__ .venv .pytest_cache .mypy_cache .ruff_cache node_modules tests migrations `
      /XF *.pyc *.db *.token launcher.toml bridge.toml | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $dir failed ($LASTEXITCODE)" }
  }
  $global:LASTEXITCODE = 0

  $env:UV_PYTHON_INSTALL_DIR = Join-Path $stand 'python'
  # Short path on purpose: some packages are built from source and break the 260-character limit
  # when the repository lies deep in a user folder. The cache is copied into the bundle afterwards.
  $workCache = Join-Path ([IO.Path]::GetPathRoot($stand)) 'ntb-uv-cache'
  if (Test-Path $workCache) { Remove-Item -Recurse -Force $workCache }
  $env:UV_CACHE_DIR = $workCache
  $env:UV_PROJECT_ENVIRONMENT = Join-Path ([IO.Path]::GetTempPath()) 'neurotlon-stand-venv'
  try {
    Run { & (Join-Path $stand 'uv.exe') python install 3.12 } 'uv python install'
    Push-Location $src
    try {
      # Fills the cache with every wheel the stand needs; the venv itself is thrown away.
      Run {
        & (Join-Path $stand 'uv.exe') sync --locked --all-packages --no-dev `
          --no-install-package neurotlon_server
      } 'uv sync'
    } finally { Pop-Location }
    robocopy $workCache (Join-Path $stand 'uv-cache') /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy cache failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
  } finally {
    Remove-Item -Recurse -Force $workCache -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    Remove-Item Env:UV_PYTHON_INSTALL_DIR, Env:UV_CACHE_DIR, Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
  }
}

Step 'Done'
$size = (Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Bundle: {0}  ({1:N0} MB). Copy the whole folder to the USB drive." -f $OutDir, $size)
