<#
.SYNOPSIS
  Installs the launcher, the BCI bridge and the games on a stand PC, with no internet.

.DESCRIPTION
  Run from the stand\ folder of the bundle (the USB drive). It copies the sources and Python to
  -InstallDir, builds the environment from the bundled wheel cache (uv sync --offline) and writes
  launcher.toml / bridge.toml from the examples. The station token is NOT asked for: save it
  from the admin panel into InstallDir\station.token yourself (one line).

  Start after installation:
    InstallDir\start-bridge.cmd     (BCI bridge; edit serial numbers in bridge.toml first)
    InstallDir\start-launcher.cmd

.EXAMPLE
  .\install-stand.ps1 -Discipline darts -ServerUrl https://neurotlon.local -CaFile D:\rootCA.pem
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][ValidateSet('darts', 'football', 'pong')][string]$Discipline,
  [Parameter(Mandatory = $true)][string]$ServerUrl,
  [string]$CaFile,
  [string]$InstallDir = 'C:\neurotlon',
  [switch]$InstallCa
)

$ErrorActionPreference = 'Stop'
$bundle = $PSScriptRoot
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
foreach ($needed in 'uv.exe', 'python', 'uv-cache', 'neurotlon') {
  if (-not (Test-Path (Join-Path $bundle $needed))) {
    throw "'$needed' not found next to the script. Run it from the stand folder of the bundle."
  }
}
if ($ServerUrl -notmatch '^https://') { throw 'ServerUrl must start with https://' }

function Run([scriptblock]$cmd, [string]$what) {
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

$app = Join-Path $InstallDir 'app'
$pythonDir = Join-Path $InstallDir 'python'
$uv = Join-Path $InstallDir 'uv.exe'
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host '== Copying files'
Copy-Item (Join-Path $bundle 'uv.exe') $uv -Force
robocopy (Join-Path $bundle 'python') $pythonDir /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy python failed ($LASTEXITCODE)" }
robocopy (Join-Path $bundle 'neurotlon') $app /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy sources failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

# uv writes lock files into its cache, and a USB drive may be read-only: work on a copy.
$cache = Join-Path ([IO.Path]::GetTempPath()) 'neurotlon-uv-cache'
if (Test-Path $cache) { Remove-Item -Recurse -Force $cache }
Write-Host '== Copying the wheel cache'
robocopy (Join-Path $bundle 'uv-cache') $cache /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy cache failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

Write-Host '== Installing packages (offline)'
$env:UV_PYTHON_INSTALL_DIR = $pythonDir
$env:UV_PYTHON_DOWNLOADS = 'never'
$env:UV_CACHE_DIR = $cache
Push-Location $app
try {
  Run { & $uv sync --offline --locked --all-packages --no-dev --no-install-package neurotlon_server } 'uv sync --offline'
} finally {
  Pop-Location
  Remove-Item Env:UV_PYTHON_INSTALL_DIR, Env:UV_PYTHON_DOWNLOADS, Env:UV_CACHE_DIR -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $cache -ErrorAction SilentlyContinue
}

Write-Host '== Writing settings'
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Toml([string]$path) { return $path.Replace('\', '/') }

if ($CaFile) {
  Copy-Item $CaFile (Join-Path $InstallDir 'rootCA.pem') -Force
  if ($InstallCa) {
    Run { certutil -addstore -f Root (Join-Path $InstallDir 'rootCA.pem') | Out-Null } 'certutil (run as administrator)'
  }
}

$launcherToml = Join-Path $InstallDir 'launcher.toml'
if (-not (Test-Path $launcherToml)) {
  $text = [IO.File]::ReadAllText((Join-Path $app 'launcher\launcher.example.toml'), $utf8)
  $text = $text -replace '(?m)^server_url = "[^"]*"', ('server_url = "{0}"' -f $ServerUrl)
  $caValue = ''
  if ($CaFile) { $caValue = Toml (Join-Path $InstallDir 'rootCA.pem') }
  $text = $text -replace '(?m)^ca_file = "[^"]*"', ('ca_file = "{0}"' -f $caValue)
  $text = $text -replace '(?m)^token_file = "[^"]*"', ('token_file = "{0}"' -f (Toml (Join-Path $InstallDir 'station.token')))
  $text = $text -replace '(?m)^discipline = "[^"]*"', ('discipline = "{0}"' -f $Discipline)
  $text = $text -replace '(?m)^data_dir = "[^"]*"', ('data_dir = "{0}"' -f (Toml (Join-Path $InstallDir 'data')))
  [IO.File]::WriteAllText($launcherToml, $text, $utf8)
} else {
  Write-Host "launcher.toml exists, left as is."
}

$bridgeToml = Join-Path $InstallDir 'bridge.toml'
if (-not (Test-Path $bridgeToml)) {
  Copy-Item (Join-Path $app 'bci-bridge\bridge.example.toml') $bridgeToml
}

$launcherCmd = "@echo off`r`ncd /d `"$InstallDir`"`r`n`"$uv`" run --offline --no-sync --project `"$app`" neurotlon-launcher --config `"$launcherToml`"`r`n"
$bridgeCmd = "@echo off`r`ncd /d `"$InstallDir`"`r`n`"$uv`" run --offline --no-sync --project `"$app`" neurotlon-bridge --profile $Discipline --config `"$bridgeToml`"`r`n"
[IO.File]::WriteAllText((Join-Path $InstallDir 'start-launcher.cmd'), $launcherCmd)
[IO.File]::WriteAllText((Join-Path $InstallDir 'start-bridge.cmd'), $bridgeCmd)

Write-Host ''
Write-Host "Installed to $InstallDir (discipline: $Discipline)."
Write-Host 'Next steps:'
Write-Host "  1. Save the station token from the admin panel into $InstallDir\station.token (one line)."
Write-Host "  2. Find the sensors:  $InstallDir\start-bridge.cmd needs serial numbers in $bridgeToml"
Write-Host "     (scan: `"$uv`" run --offline --no-sync --project `"$app`" neurotlon-bridge --scan)"
Write-Host '  3. If the CA is not installed on this PC: rerun with -InstallCa as administrator, or keep ca_file in launcher.toml.'
Write-Host "  4. Start start-bridge.cmd, then start-launcher.cmd."
