<#
.SYNOPSIS
  Creates the local certificate authority and the server certificate with mkcert.

.DESCRIPTION
  Output (deploy\certs, never committed):
    server.pem, server-key.pem  - for Nginx (mounted into the web container)
    rootCA.pem, rootCA.crt      - the CA to install on tablets and stands (same file, two names)
  The certificate covers HOST_NAME, the LAN IP of this PC, localhost, 127.0.0.1 and -ExtraNames
  (put the spare laptop's name or IP there so it can take over without new certificates on tablets).
  mkcert.exe is downloaded beforehand onto the USB drive (https://github.com/FiloSottile/mkcert/releases)
  and lives next to this script, in .\tools, or in PATH.
  The CA private key stays in the mkcert folder of this PC (mkcert -CAROOT). Never copy it to tablets.

.EXAMPLE
  .\make-certs.ps1 -HostName neurotlon.local
#>
[CmdletBinding()]
param(
  [string]$HostName,
  [string]$Ip,
  [string[]]$ExtraNames = @(),
  [string]$MkcertPath,
  [string]$OutDir,
  [switch]$Force,
  [switch]$SkipInstallCa
)

$ErrorActionPreference = 'Stop'
$deployDir = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $deployDir 'certs' }

function Get-EnvValue([string]$name) {
  $file = Join-Path $deployDir '.env'
  if (-not (Test-Path $file)) { return $null }
  foreach ($line in Get-Content $file) {
    if ($line -match "^\s*$name\s*=\s*(.+?)\s*$") { return $Matches[1] }
  }
  return $null
}

if (-not $HostName) { $HostName = Get-EnvValue 'HOST_NAME' }
if (-not $HostName) { $HostName = 'neurotlon.local' }

if (-not $Ip) {
  # The address that has the default gateway is the one in the hall network.
  $config = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | Select-Object -First 1
  if ($config) { $Ip = $config.IPv4Address[0].IPAddress }
}
if (-not $Ip) {
  Write-Warning 'LAN IP not found (no network?). The certificate will not cover an IP address; pass -Ip 192.168.x.x.'
}

if (-not $MkcertPath) {
  $candidates = @(
    (Join-Path $PSScriptRoot 'mkcert.exe'),
    (Join-Path $PSScriptRoot 'tools\mkcert.exe'),
    (Join-Path $deployDir 'tools\mkcert.exe')
  )
  $MkcertPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $MkcertPath) {
    $found = Get-Command mkcert -ErrorAction SilentlyContinue
    if ($found) { $MkcertPath = $found.Source }
  }
}
if (-not $MkcertPath -or -not (Test-Path $MkcertPath)) {
  throw 'mkcert.exe not found. Download it beforehand and put it next to this script (see deploy/README.md).'
}

$cert = Join-Path $OutDir 'server.pem'
$key = Join-Path $OutDir 'server-key.pem'
if ((Test-Path $cert) -and (Test-Path $key) -and -not $Force) {
  Write-Host "Certificate already exists in $OutDir (use -Force to make a new one)."
  return
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not $SkipInstallCa) {
  # Puts the CA into this PC's trust store so the admin's own browser accepts the site.
  & $MkcertPath -install
  if ($LASTEXITCODE -ne 0) { throw 'mkcert -install failed' }
}

$names = @($HostName, 'localhost', '127.0.0.1')
if ($Ip) { $names += $Ip }
$names += $ExtraNames   # e.g. the IP of the spare laptop
& $MkcertPath -cert-file $cert -key-file $key @names
if ($LASTEXITCODE -ne 0) { throw 'mkcert failed to create the certificate' }

$caRoot = (& $MkcertPath -CAROOT).Trim()
Copy-Item (Join-Path $caRoot 'rootCA.pem') (Join-Path $OutDir 'rootCA.pem') -Force
Copy-Item (Join-Path $caRoot 'rootCA.pem') (Join-Path $OutDir 'rootCA.crt') -Force

Write-Host ''
Write-Host "Certificate for: $($names -join ', ')"
Write-Host "Server files:    $cert, $key"
Write-Host "CA for devices:  $(Join-Path $OutDir 'rootCA.crt')"
Write-Host '  Android tablet: copy rootCA.crt, Settings > Security > Install certificate > CA certificate.'
Write-Host '  Windows stand:  certutil -addstore Root rootCA.crt   (as administrator),'
Write-Host '                  or set ca_file in launcher.toml to the path of rootCA.pem.'
Write-Host "Keep the CA private key ($caRoot\rootCA-key.pem) on this PC only."
