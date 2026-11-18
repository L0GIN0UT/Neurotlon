<#
.SYNOPSIS
  Installs and starts Neurotlon on the admin PC from the bundle. No internet needed.

.DESCRIPTION
  Run from the bundle folder (USB drive or its copy), with Docker Desktop running:
    powershell -ExecutionPolicy Bypass -File scripts\install-admin.ps1
  Steps: load the images, create .env from .env.example, make the certificate if missing,
  open the firewall for ports 80 and 443 (when run as administrator), docker compose up -d,
  wait for the services to become healthy, print the addresses and the next steps.
  Safe to run again: it never deletes data.

.PARAMETER NonInteractive
  Do not pause to let you edit .env (use after .env is already filled in).
#>
[CmdletBinding()]
param(
  [string]$BundleDir,
  [switch]$NonInteractive,
  [int]$WaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
if (-not $BundleDir) { $BundleDir = Split-Path -Parent $PSScriptRoot }
$BundleDir = (Resolve-Path $BundleDir).Path

function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Run([scriptblock]$cmd, [string]$what) {
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}
function Get-EnvValue([string]$name) {
  $file = Join-Path $BundleDir '.env'
  foreach ($line in Get-Content $file) {
    if ($line -match "^\s*$name\s*=\s*(.+?)\s*$") { return $Matches[1] }
  }
  return $null
}

Step 'Checking Docker'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker is not installed. Install Docker Desktop (WSL2 backend) first.'
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running. Start it, wait for "Engine running", and run this script again.' }
docker version --format '{{.Server.Os}}' | ForEach-Object {
  if ($_ -ne 'linux') { throw 'Docker is in Windows containers mode. Switch to Linux containers (tray icon menu).' }
}

Step 'Loading images'
$tar = Join-Path $BundleDir 'neurotlon-images.tar'
if (Test-Path $tar) {
  $sums = Join-Path $BundleDir 'SHA256SUMS.txt'
  if (Test-Path $sums) {
    $expected = ((Get-Content $sums | Select-Object -First 1) -split '\s+')[0].ToLower()
    $actual = (Get-FileHash $tar -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { throw 'neurotlon-images.tar is damaged (checksum mismatch). Copy the bundle again.' }
    Write-Host 'Checksum OK.'
  }
  Run { docker load -i $tar } 'docker load'
} else {
  docker image inspect neurotlon-server:local neurotlon-web:local *> $null
  if ($LASTEXITCODE -ne 0) { throw "neurotlon-images.tar not found in $BundleDir and the images are not loaded." }
  Write-Host 'No tar file; the images are already loaded.'
}

Step 'Settings (.env)'
$envFile = Join-Path $BundleDir '.env'
if (-not (Test-Path $envFile)) {
  Copy-Item (Join-Path $BundleDir '.env.example') $envFile
  Write-Host "Created $envFile"
  if (-not $NonInteractive) {
    Write-Host 'Set HOST_NAME and BACKUP_DIR (the USB drive or folder for backups) in this file.'
    Start-Process notepad.exe $envFile -Wait
  }
}
$hostName = Get-EnvValue 'HOST_NAME'
$backupDir = Get-EnvValue 'BACKUP_DIR'
if (-not $hostName) { throw 'HOST_NAME is not set in .env' }
if ($backupDir -and ($backupDir -match '^[A-Za-z]:' -or $backupDir.StartsWith('\\')) -and -not (Test-Path $backupDir)) {
  throw "BACKUP_DIR '$backupDir' does not exist. Plug in the backup drive or fix .env."
}

Step 'Certificate'
if (-not (Test-Path (Join-Path $BundleDir 'certs\server.pem'))) {
  & (Join-Path $PSScriptRoot 'make-certs.ps1') -HostName $hostName -OutDir (Join-Path $BundleDir 'certs')
} else {
  Write-Host 'certs\server.pem exists, keeping it.'
}

Step 'Firewall'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  if (-not (Get-NetFirewallRule -DisplayName 'Neurotlon HTTP/HTTPS' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName 'Neurotlon HTTP/HTTPS' -Direction Inbound -Protocol TCP `
      -LocalPort 80, 443 -Action Allow -Profile Any | Out-Null
    Write-Host 'Inbound rule for TCP 80 and 443 added.'
  } else {
    Write-Host 'Firewall rule already exists.'
  }
} else {
  Write-Warning 'Not running as administrator: allow TCP ports 80 and 443 in Windows Firewall yourself, or rerun as administrator.'
}

Step 'Starting'
Push-Location $BundleDir
try {
  Run { docker compose up -d --no-build } 'docker compose up'

  $deadline = (Get-Date).AddSeconds($WaitSeconds)
  $healthy = $false
  while ((Get-Date) -lt $deadline) {
    $states = foreach ($service in 'server', 'web') {
      $id = (docker compose ps -q $service | Select-Object -First 1)
      if ($id) { (docker inspect -f '{{.State.Health.Status}}' $id) } else { 'missing' }
    }
    if (($states | Where-Object { $_ -ne 'healthy' }).Count -eq 0) { $healthy = $true; break }
    Start-Sleep -Seconds 3
  }
  if (-not $healthy) {
    docker compose ps
    throw "Services are not healthy after $WaitSeconds s. See: docker compose logs"
  }
} finally { Pop-Location }

$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
  Select-Object -First 1).IPv4Address.IPAddress

Write-Host ''
Write-Host 'Neurotlon is running.' -ForegroundColor Green
foreach ($base in "https://$hostName", $(if ($ip) { "https://$ip" })) {
  if (-not $base) { continue }
  Write-Host "  $base/admin   $base/judge   $base/board   $base/tablet"
}
Write-Host ''
Write-Host 'Next steps:'
Write-Host '  1. Create the superuser (asks for a password, 8+ characters):'
Write-Host "       cd `"$BundleDir`""
Write-Host '       docker compose exec server neurotlon-server create-superuser --login root'
Write-Host "  2. Install $BundleDir\certs\rootCA.crt on every tablet and stand (see README, section on certificates)."
Write-Host '  3. Check the backups:  docker compose logs --tail 5 backup'
Write-Host '  4. Run the rehearsal on an empty database (see README).'
