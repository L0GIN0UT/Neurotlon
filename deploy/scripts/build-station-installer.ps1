<#
.SYNOPSIS
  Собирает установщик стенда для Windows: «Нейротлон Стенд» + ядро лаунчера + мост датчиков + все игры.

.DESCRIPTION
  Что делает:
    1. собирает интерфейс окна (web) и кладёт его в установщик;
    2. упаковывает Python-ядро лаунчера и мост датчиков в .exe (PyInstaller);
    3. берёт собранные игры из games\builds (их делает games\build-games.ps1);
    4. собирает один установщик Electron (NSIS) с нашей иконкой: нужная игра выбирается
       на стенде по дисциплине станции, которую сообщает сервер по токену.

  Нужен интернет (npm, PyInstaller, движок Electron, NSIS). Готовые установщики лежат в
  launcher\electron\dist и переносятся на стенды без интернета: на стенде достаточно запустить
  установщик, при первом запуске админ вводит адрес сервера и токен станции.

.EXAMPLE
  .\build-station-installer.ps1                    # установщик со всеми тремя играми
  .\build-station-installer.ps1 -Games Pong        # только с понгом (для проверки)
  .\build-station-installer.ps1 -SkipWeb -SkipCore # интерфейс и ядро уже собраны
#>
[CmdletBinding()]
param(
    [ValidateSet('Darts', 'Football', 'Pong')]
    [string[]] $Games = @('Darts', 'Football', 'Pong'),
    [switch] $SkipWeb,
    [switch] $SkipCore,
    [string] $BuildsDir = ''
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$electron = Join-Path $repo 'launcher\electron'
$stage = Join-Path $electron 'stage'
if (-not $BuildsDir) { $BuildsDir = Join-Path $repo 'games\builds' }

function Invoke-Step([string] $Title, [scriptblock] $Action) {
    Write-Host "== $Title"
    # Windows PowerShell 5.1 считает любой вывод native-программы в stderr ошибкой: проверяем код выхода.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0
    try { & $Action } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "Шаг «$Title» завершился с кодом $LASTEXITCODE" }
}

# Нужные сборки игр проверяем сразу, чтобы не ждать конца долгих шагов.
foreach ($game in $Games) {
    $exe = Join-Path $BuildsDir "$game\$game.exe"
    if (-not (Test-Path $exe)) { throw "Нет сборки $game ($exe). Сначала: games\build-games.ps1 -Games $game (или -BuildsDir)" }
}

New-Item -ItemType Directory -Force $stage | Out-Null

if (-not $SkipWeb) {
    Invoke-Step 'Интерфейс окна (web)' {
        Push-Location (Join-Path $repo 'web')
        try { npm ci; if ($LASTEXITCODE -eq 0) { npm run build } } finally { Pop-Location }
    }
}
$webDist = Join-Path $repo 'web\dist'
if (-not (Test-Path (Join-Path $webDist 'station.html'))) { throw "Нет web\dist\station.html: соберите интерфейс (без -SkipWeb)" }
Remove-Item (Join-Path $stage 'web') -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $webDist (Join-Path $stage 'web') -Recurse

if (-not $SkipCore) {
    Invoke-Step 'Ядро лаунчера (PyInstaller)' {
        $work = Join-Path $env:TEMP 'neurotlon-core-build'
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
        Push-Location $repo
        try {
            uv run --with pyinstaller pyinstaller --noconfirm --onedir --name neurotlon-launcher `
                --paths launcher\src --paths shared\python\src `
                --add-data "$repo\shared\game-launch.schema.json;shared" `
                --add-data "$repo\shared\bridge-protocol.schema.json;shared" `
                --collect-data jsonschema_specifications --collect-data jsonschema `
                --exclude-module numpy --exclude-module PIL --exclude-module yaml `
                --exclude-module pygame --exclude-module scipy --exclude-module cv2 `
                --distpath "$work\out" --workpath "$work\work" --specpath "$work\spec" `
                launcher\station_core.py
        } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { return }
        Remove-Item (Join-Path $stage 'core') -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item "$work\out\neurotlon-launcher" (Join-Path $stage 'core') -Recurse
    }
}
if (-not $SkipCore) {
    Invoke-Step 'Мост датчиков (PyInstaller)' {
        $work = Join-Path $env:TEMP 'neurotlon-bridge-build'
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
        Push-Location $repo
        try {
            uv run --with pyinstaller pyinstaller --noconfirm --onedir --name neurotlon-bridge `
                --paths bci-bridge\src --collect-all neurosdk --collect-all em_st_artifacts `
                --distpath "$work\out" --workpath "$work\work" --specpath "$work\spec" `
                bci-bridge\station_bridge.py
        } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { return }
        Remove-Item (Join-Path $stage 'bridge') -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item "$work\out\neurotlon-bridge" (Join-Path $stage 'bridge') -Recurse
    }
}
if (-not (Test-Path (Join-Path $stage 'core\neurotlon-launcher.exe'))) { throw 'Нет ядра лаунчера (stage\core): соберите без -SkipCore' }
foreach ($schema in 'game-launch', 'bridge-protocol') {
    if (-not (Test-Path (Join-Path $stage "core\_internal\shared\$schema.schema.json"))) { throw "В ядре лаунчера нет shared\$schema.schema.json: проверьте --add-data в сборке ядра" }
}
if (-not (Test-Path (Join-Path $stage 'bridge\neurotlon-bridge.exe'))) { throw 'Нет моста датчиков (stage\bridge): соберите без -SkipCore' }

Invoke-Step 'Зависимости оболочки Electron' {
    Push-Location $electron
    try { npm ci } finally { Pop-Location }
}

Invoke-Step 'Игры' {
    $target = Join-Path $stage 'games'
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $target | Out-Null
    foreach ($game in $Games) {
        # Папка *_BackUpThisFolder_* нужна разработчику Unity, на стенде она не нужна.
        $to = Join-Path $target $game
        New-Item -ItemType Directory -Force $to | Out-Null
        Get-ChildItem (Join-Path $BuildsDir $game) |
            Where-Object { $_.Name -notlike '*_BackUpThisFolder_*' -and $_.Name -ne '_logs' } |
            Copy-Item -Destination $to -Recurse
    }
}

Invoke-Step 'Установщик (NSIS)' {
    Push-Location $electron
    try {
        npx electron-builder --win "--config.nsis.artifactName=Neurotlon-Station-Setup-`${version}.exe"
    } finally { Pop-Location }
}

Write-Host ''
Write-Host 'Готово. Установщик:'
Get-ChildItem (Join-Path $electron 'dist') -Filter '*Setup*.exe' | ForEach-Object {
    Write-Host ('  {0}  ({1} МБ)' -f $_.FullName, [math]::Round($_.Length / 1MB))
}
