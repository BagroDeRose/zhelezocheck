<#
.SYNOPSIS
    Скачивает сторонние программы для ЖелезоЧек в папку vendor\ и проверяет их контрольные суммы.

.DESCRIPTION
    Что скачивается (только официальные релизы на GitHub):
      * memtest_vulkan (тест видеопамяти, лицензия zlib)
        https://github.com/GpuZelenograd/memtest_vulkan/releases
        SHA-256 опубликована самим GitHub для файла релиза и зашита ниже.
      * smartmontools / smartctl (чтение S.M.A.R.T., лицензия GPL-2.0)
        https://github.com/smartmontools/smartmontools/releases
        Установщик НЕ запускается: smartctl.exe извлекается из него программой 7-Zip.
        Проверяется MD5 установщика (официальный файл .md5 из релиза) и MD5 самого
        smartctl.exe (официальный doc\checksums64.txt внутри установщика).

    Все итоговые файлы дополнительно сверяются с vendor\CHECKSUMS.txt (SHA-256).
    Если файла в списке ещё нет — сумма вычисляется и ДОПИСЫВАЕТСЯ; владелец проекта
    должен один раз подтвердить её (см. docs\HUMAN_TODO.md). Если сумма не совпадает с
    уже записанной — скрипт останавливается с ошибкой.

    Скрипт ничего не устанавливает в систему и не требует прав администратора.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_vendor.ps1
#>
[CmdletBinding()]
param(
    [switch]$Force  # скачать заново, даже если файлы уже есть
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
$Vendor = Join-Path $Root 'vendor'
$Downloads = Join-Path $Vendor '_downloads'
$ChecksumFile = Join-Path $Vendor 'CHECKSUMS.txt'

# --- Версии и официальные суммы -------------------------------------------------
$MemtestVersion = 'v0.5.0'
$MemtestUrl = "https://github.com/GpuZelenograd/memtest_vulkan/releases/download/$MemtestVersion/memtest_vulkan-$MemtestVersion.exe"
$MemtestLicenseUrl = "https://raw.githubusercontent.com/GpuZelenograd/memtest_vulkan/$MemtestVersion/LICENSE"
# Значение поля "digest" файла релиза в GitHub API.
$MemtestSha256 = '09e67704210762ae8d8ad70fe6d71275eefbe815cc2c0658cd5afc8e231d0df6'

$SmartVersion = '7.5'
$SmartTag = 'RELEASE_7_5'
$SmartUrl = "https://github.com/smartmontools/smartmontools/releases/download/$SmartTag/smartmontools-$SmartVersion.win32-setup.exe"

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Get-Sha256([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower() }
function Get-Md5([string]$Path) { (Get-FileHash -Algorithm MD5 -LiteralPath $Path).Hash.ToLower() }

function Get-Download([string]$Url, [string]$Target) {
    if ((Test-Path $Target) -and -not $Force) { return }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
    Write-Host "    скачиваю $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Target
}

function Read-KnownChecksums {
    $known = @{}
    if (Test-Path $ChecksumFile) {
        foreach ($line in Get-Content -LiteralPath $ChecksumFile -Encoding UTF8) {
            if ($line -match '^\s*#' -or $line.Trim() -eq '') { continue }
            $parts = $line.Trim() -split '\s+', 2
            if ($parts.Count -eq 2) { $known[$parts[1]] = $parts[0].ToLower() }
        }
    }
    return $known
}

function Confirm-Checksum([string]$Path) {
    $relative = $Path.Substring($Vendor.Length + 1).Replace('\', '/')
    $actual = Get-Sha256 $Path
    $known = Read-KnownChecksums
    if ($known.ContainsKey($relative)) {
        if ($known[$relative] -ne $actual) {
            throw "Контрольная сумма $relative НЕ совпадает с CHECKSUMS.txt! Ожидалось $($known[$relative]), получено $actual. Файл не используем."
        }
        Write-Host "    OK  $relative"
    } else {
        Add-Content -LiteralPath $ChecksumFile -Encoding UTF8 -Value "$actual  $relative"
        Write-Host "    НОВАЯ сумма записана в CHECKSUMS.txt: $relative" -ForegroundColor Yellow
    }
}

function Find-SevenZip {
    $candidates = @(
        (Join-Path $env:ProgramFiles '7-Zip\7z.exe'),
        (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
    )
    foreach ($candidate in $candidates) { if ($candidate -and (Test-Path $candidate)) { return $candidate } }
    $command = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

New-Item -ItemType Directory -Force -Path $Vendor, $Downloads | Out-Null
if (-not (Test-Path $ChecksumFile)) {
    Set-Content -LiteralPath $ChecksumFile -Encoding UTF8 -Value @(
        '# SHA-256 сторонних программ в vendor\. Формат: <sha256>  <путь относительно vendor>',
        '# Новые строки дописывает scripts\setup_vendor.ps1; владелец подтверждает их один раз.'
    )
}

# --- memtest_vulkan --------------------------------------------------------------
Write-Step "memtest_vulkan $MemtestVersion"
$MemtestDir = Join-Path $Vendor 'memtest_vulkan'
$MemtestExe = Join-Path $MemtestDir 'memtest_vulkan.exe'
Get-Download $MemtestUrl $MemtestExe
if ((Get-Sha256 $MemtestExe) -ne $MemtestSha256) {
    Remove-Item -LiteralPath $MemtestExe -Force
    throw 'SHA-256 memtest_vulkan не совпадает с официальной суммой из релиза GitHub. Файл удалён.'
}
Write-Host '    SHA-256 совпадает с официальной суммой релиза'
Confirm-Checksum $MemtestExe
Get-Download $MemtestLicenseUrl (Join-Path $MemtestDir 'LICENSE.txt')

# --- smartmontools -----------------------------------------------------------------
Write-Step "smartmontools $SmartVersion"
$SmartDir = Join-Path $Vendor 'smartmontools'
$Installer = Join-Path $Downloads "smartmontools-$SmartVersion.win32-setup.exe"
$InstallerMd5File = "$Installer.md5"
Get-Download $SmartUrl $Installer
Get-Download "$SmartUrl.md5" $InstallerMd5File
$officialMd5 = ((Get-Content -LiteralPath $InstallerMd5File -Raw).Trim() -split '\s+')[0].ToLower()
if ((Get-Md5 $Installer) -ne $officialMd5) {
    Remove-Item -LiteralPath $Installer -Force
    throw 'MD5 установщика smartmontools не совпадает с официальным. Файл удалён.'
}
Write-Host '    MD5 установщика совпадает с официальным'

$SevenZip = Find-SevenZip
if (-not $SevenZip) {
    throw 'Нужен 7-Zip (https://www.7-zip.org), чтобы извлечь smartctl.exe без установки smartmontools.'
}
$Extract = Join-Path $Downloads 'smartmontools_extract'
if (Test-Path $Extract) { Remove-Item -Recurse -Force -LiteralPath $Extract }
& $SevenZip x -y "-o$Extract" $Installer 'bin\smartctl.exe' 'doc\COPYING.txt' 'doc\checksums64.txt' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "7-Zip не смог распаковать установщик (код $LASTEXITCODE)" }

$officialList = Get-Content -LiteralPath (Join-Path $Extract 'doc\checksums64.txt')
$expectedMd5 = ($officialList | Where-Object { $_ -match '^[0-9a-f]{32}\s+smartctl\.exe$' } | Select-Object -First 1) -split '\s+' | Select-Object -First 1
$extractedExe = Join-Path $Extract 'bin\smartctl.exe'
if (-not $expectedMd5 -or (Get-Md5 $extractedExe) -ne $expectedMd5.ToLower()) {
    throw 'MD5 smartctl.exe не совпадает с doc\checksums64.txt из установщика.'
}
Write-Host '    MD5 smartctl.exe совпадает с официальным списком'

New-Item -ItemType Directory -Force -Path (Join-Path $SmartDir 'bin') | Out-Null
Copy-Item -Force -LiteralPath $extractedExe -Destination (Join-Path $SmartDir 'bin\smartctl.exe')
Copy-Item -Force -LiteralPath (Join-Path $Extract 'doc\COPYING.txt') -Destination (Join-Path $SmartDir 'COPYING.txt')
Set-Content -LiteralPath (Join-Path $SmartDir 'SOURCE.txt') -Encoding UTF8 -Value @(
    "smartmontools $SmartVersion (GPL-2.0). Исходный код: https://github.com/smartmontools/smartmontools/releases/tag/$SmartTag",
    "smartctl.exe извлечён из официального установщика $SmartUrl без его запуска."
)
Confirm-Checksum (Join-Path $SmartDir 'bin\smartctl.exe')
Remove-Item -Recurse -Force -LiteralPath $Extract

Write-Step 'Готово. Сторонние программы лежат в vendor\.'
