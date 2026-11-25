<#
.SYNOPSIS
  Собирает Unity-игры (дартс, футбол, понг) в Windows .exe без открытия редактора.

.DESCRIPTION
  Результат: games\builds\<Игра>\<Игра>.exe со всеми файлами рядом (копировать надо всю папку).
  Нужен установленный Unity нужной версии; закройте редактор на этих проектах: второй
  экземпляр на тот же проект Unity не запускает. Сборка каждой игры занимает несколько минут.

.EXAMPLE
  .\build-games.ps1                      # все три игры
  .\build-games.ps1 -Games Pong,Darts    # только некоторые
#>
[CmdletBinding()]
param(
    [ValidateSet('Darts', 'Football', 'Pong')]
    [string[]] $Games = @('Darts', 'Football', 'Pong'),
    [string] $UnityVersion = '6000.6.9f1',
    [string] $UnityExe = "C:\Program Files\Unity\Hub\Editor\$UnityVersion\Editor\Unity.exe",
    [string] $OutRoot = ''
)

$ErrorActionPreference = 'Stop'
# Значение по умолчанию считаем здесь, а не в параметре: в Windows PowerShell 5.1 $PSScriptRoot в выражении
# параметра оказался пустым (замечено при кириллице в пути к проекту).
if (-not $OutRoot) { $OutRoot = Join-Path $PSScriptRoot 'builds' }
if (-not (Test-Path $UnityExe)) { throw "Unity не найден: $UnityExe (параметр -UnityExe или -UnityVersion)" }
if (Get-Process -Name Unity -ErrorAction SilentlyContinue) {
    throw 'Запущен редактор Unity: закройте его, пакетная сборка не стартует на открытом проекте.'
}

$logs = Join-Path $OutRoot '_logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$failed = @()

foreach ($game in $Games) {
    $project = Join-Path $PSScriptRoot "unity\$game"
    $out = Join-Path $OutRoot $game
    $log = Join-Path $logs "$game.log"
    if (Test-Path $out) { Remove-Item $out -Recurse -Force }
    Write-Host "== ${game}: сборка (журнал $log)"
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $UnityExe -Wait -PassThru -ArgumentList @(
        '-batchmode', '-quit', '-projectPath', "`"$project`"",
        '-executeMethod', 'Neurotlon.Kit.Editor.NeurotlonBuild.BuildWindows64',
        '-neurotlonOut', "`"$out`"", '-logFile', "`"$log`""
    )
    $exe = Join-Path $out "$game.exe"
    if ($process.ExitCode -ne 0 -or -not (Test-Path $exe)) {
        Write-Warning "${game}: сборка не удалась (код $($process.ExitCode)), см. $log"
        $failed += $game
        continue
    }
    $size = [math]::Round(((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB)
    Write-Host ("   готово за {0:n0} с: {1} ({2} МБ)" -f $watch.Elapsed.TotalSeconds, $exe, $size)
}

if ($failed.Count -gt 0) { throw "Не собраны: $($failed -join ', ')" }
Write-Host "Все игры собраны в $OutRoot"
