<#
.SYNOPSIS
    Собирает портативную версию ЖелезоЧек в dist\ЖелезоЧек\ (для копирования на флешку).

.DESCRIPTION
    1. PyInstaller по packaging\hwcheck.spec (папка с exe, без установки).
    2. Докладывает в _internal\vendor сторонние программы (memtest_vulkan, smartctl)
       с проверкой SHA-256 по vendor\CHECKSUMS.txt и лицензии; рядом с exe кладёт ПРОЧТИ.txt.
       Наверху папки — только ЖелезоЧек.exe, ПРОЧТИ.txt, ЛИЦЕНЗИЯ.txt и _internal (формат 18.1, SPEC 1.4 — 30.2).
    3. Запускает самопроверку собранной программы в демо-режиме (--demo --smoke-test)
       во временной папке данных — в dist\ ничего лишнего не остаётся.
    4. Печатает размер сборки.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$AppName = 'ЖелезоЧек'
$Dist = Join-Path $Root "dist\$AppName"
$Internal = Join-Path $Dist '_internal'

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

Write-Step 'Сборка PyInstaller'
# Все временные файлы и кэш PyInstaller — внутри проекта (.tmp), а не в профиле Windows.
$ProjectTmp = Join-Path $Root '.tmp'
New-Item -ItemType Directory -Force -Path $ProjectTmp | Out-Null
$env:PYINSTALLER_CONFIG_DIR = Join-Path $ProjectTmp 'pyinstaller'
$env:TEMP = $ProjectTmp
$env:TMP = $ProjectTmp
& $Python -m PyInstaller --noconfirm --clean packaging\hwcheck.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с кодом $LASTEXITCODE" }

Write-Step 'Сторонние программы и лицензии'
$Checksums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $Root 'vendor\CHECKSUMS.txt') -Encoding UTF8) {
    if ($line -match '^([0-9a-f]{64})\s+(\S+)$') { $Checksums[$Matches[2]] = $Matches[1] }
}
$VendorFiles = @('memtest_vulkan/memtest_vulkan.exe', 'smartmontools/bin/smartctl.exe')
foreach ($relative in $VendorFiles) {
    $source = Join-Path $Root ('vendor\' + $relative.Replace('/', '\'))
    if (-not (Test-Path $source)) {
        Write-Warning "$relative не найден — запустите scripts\setup_vendor.ps1. Сборка будет без этой программы."
        continue
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLower()
    if ($Checksums[$relative] -ne $actual) { throw "SHA-256 $relative не совпадает с vendor\CHECKSUMS.txt" }
    $target = Join-Path $Internal ('vendor\' + $relative.Replace('/', '\'))
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -Force -LiteralPath $source -Destination $target
}
foreach ($extra in @('memtest_vulkan\LICENSE.txt', 'smartmontools\COPYING.txt', 'smartmontools\SOURCE.txt')) {
    $source = Join-Path $Root "vendor\$extra"
    if (Test-Path $source) { Copy-Item -Force -LiteralPath $source -Destination (Join-Path $Internal "vendor\$extra") }
}
Copy-Item -Force -LiteralPath (Join-Path $Root 'vendor\CHECKSUMS.txt') -Destination (Join-Path $Internal 'vendor\CHECKSUMS.txt')
Copy-Item -Force -LiteralPath (Join-Path $Root 'packaging\THIRD_PARTY_NOTICES.md') -Destination $Internal

# ПРОЧТИ.txt: подставляем только версию программы.
$Version = (& $Python -c "import hwcheck; print(hwcheck.__version__)").Trim()
$Readme = (Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Root 'packaging\ПРОЧТИ.txt')).Replace('{VERSION}', $Version)
$Readme = $Readme.Replace("`r`n", "`n").Replace("`n", "`r`n")  # Блокнот: переводы строк Windows
[System.IO.File]::WriteAllText((Join-Path $Dist 'ПРОЧТИ.txt'), $Readme, (New-Object System.Text.UTF8Encoding $true))

# LICENSE (MIT): в корне архива рядом с exe; THIRD_PARTY_NOTICES.md — в _internal.
$License = (Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Root 'LICENSE'))
$License = $License.Replace("`r`n", "`n").Replace("`n", "`r`n")
[System.IO.File]::WriteAllText((Join-Path $Dist 'LICENSE'), $License, (New-Object System.Text.UTF8Encoding $true))

if (-not $SkipSmokeTest) {
    Write-Step 'Самопроверка сборки (демо-режим)'
    $TempRoot = Join-Path $ProjectTmp ('smoke_' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    try {
        $env:HWCHECK_ROOT = $TempRoot
        $process = Start-Process -FilePath (Join-Path $Dist "$AppName.exe") `
            -ArgumentList '--demo', 'mining_gpu', '--smoke-test' -Wait -PassThru
        $log = Join-Path $TempRoot 'data\logs\smoke_test.txt'
        if (Test-Path $log) { Get-Content -LiteralPath $log -Encoding UTF8 | Write-Host }
        # Доказательство (SPEC 1.3, 24.3): полный вывод самопроверки — в docs/qa/smoke_<версия>.txt.
        $Evidence = Join-Path $Root "docs\qa\smoke_$Version.txt"
        $Lines = @(
            "Самопроверка собранной программы ЖелезоЧек $Version",
            ('Дата: {0:dd.MM.yyyy HH:mm:ss}' -f (Get-Date)),
            "Команда: $AppName.exe --demo mining_gpu --smoke-test (папка dist\$AppName)",
            "Код выхода: $($process.ExitCode)",
            ''
        )
        if (Test-Path $log) { $Lines += Get-Content -LiteralPath $log -Encoding UTF8 }
        else { $Lines += 'Файл итога самопроверки не создан.' }
        # Снимки схемы клавиатуры из exe (25.2) — рядом, с той же версией в имени.
        Get-ChildItem -LiteralPath (Join-Path $TempRoot 'data\logs') -Filter 'keyboard_*.png' -ErrorAction SilentlyContinue |
            ForEach-Object {
                $Shot = "smoke_${Version}_$($_.Name)"
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Root "docs\qa\$Shot") -Force
                $Lines += "Снимок из exe: docs/qa/$Shot"
            }
        [System.IO.File]::WriteAllText($Evidence, (($Lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
        if ($process.ExitCode -ne 0) { throw "Самопроверка не прошла (код $($process.ExitCode))" }
    } finally {
        Remove-Item Env:HWCHECK_ROOT -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force -LiteralPath $TempRoot -ErrorAction SilentlyContinue
    }
}

$size = (Get-ChildItem -Recurse -File -LiteralPath $Dist | Measure-Object -Property Length -Sum).Sum
Write-Step ("Готово: {0} ({1:N0} МБ)" -f $Dist, ($size / 1MB))
