<#
.SYNOPSIS
    Проверка «без следов»: собранная программа не должна ничего оставлять в профиле пользователя.

.DESCRIPTION
    Делает снимок списка файлов и папок в %APPDATA%, %LOCALAPPDATA% и %TEMP% (на глубину 4),
    запускает dist\ЖелезоЧек\ЖелезоЧек.exe --demo --smoke-test, делает снимок ещё раз
    и печатает новые пути, в имени которых есть следы программы (ЖелезоЧек, hwcheck, python,
    Qt, QtWebEngine, pyinstaller/_MEI). Посторонние изменения других программ не показываются.
    Данные самой программы (папка data\ рядом с exe) после проверки удаляются.
    Код выхода: 0 — следов нет, 1 — найдены следы.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check_no_traces.ps1
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$AppName = 'ЖелезоЧек'
$Exe = Join-Path $Root "dist\$AppName\$AppName.exe"
if (-not (Test-Path $Exe)) { throw "Сначала соберите программу: scripts\build.ps1" }

$Folders = @($env:APPDATA, $env:LOCALAPPDATA, [IO.Path]::GetTempPath())
$Markers = @('ЖелезоЧек', 'hwcheck', 'zhelezo', 'python', 'qtwebengine', 'qt6', 'pyside', '_mei', 'pyinstaller')

function Get-Snapshot {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($folder in $Folders) {
        Get-ChildItem -LiteralPath $folder -Recurse -Depth 4 -Force -ErrorAction SilentlyContinue |
            ForEach-Object { [void]$set.Add($_.FullName) }
    }
    return ,$set
}

Remove-Item Env:HWCHECK_ROOT -ErrorAction SilentlyContinue
$before = Get-Snapshot
$process = Start-Process -FilePath $Exe -ArgumentList '--demo', 'mining_gpu', '--smoke-test' -Wait -PassThru
Start-Sleep -Seconds 2
$after = Get-Snapshot

$traces = @()
foreach ($path in $after) {
    if ($before.Contains($path)) { continue }
    $lower = $path.ToLower()
    if ($Markers | Where-Object { $lower.Contains($_.ToLower()) }) { $traces += $path }
}

$DataDir = Join-Path (Split-Path -Parent $Exe) 'data'
$smokeLog = Join-Path $DataDir 'logs\smoke_test.txt'
if (Test-Path $smokeLog) { Get-Content -LiteralPath $smokeLog -Encoding UTF8 | Write-Host }
Remove-Item -Recurse -Force -LiteralPath $DataDir -ErrorAction SilentlyContinue

Write-Host "Самопроверка программы: код $($process.ExitCode)"
if ($traces.Count -gt 0) {
    Write-Host 'НАЙДЕНЫ СЛЕДЫ ПРОГРАММЫ ВНЕ ЕЁ ПАПКИ:' -ForegroundColor Red
    $traces | Sort-Object | ForEach-Object { Write-Host "  $_" }
    exit 1
}
Write-Host 'Следов вне папки программы нет.' -ForegroundColor Green
exit $process.ExitCode
