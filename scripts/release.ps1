<#
.SYNOPSIS
    Сборка выпуска ЖелезоЧек: кандидат (по умолчанию) или финальный выпуск.

.DESCRIPTION
    Программа бесплатная и открытая (версия 2.0, лицензия MIT).
    Режимы:
    -Candidate (по умолчанию) — версия вида X.Y.Z-rcN. Локальный кандидат: проверки, сборка
        с самопроверкой, «без следов», архив release\candidates\ЖелезоЧек-vX.Y.Z-rcN.zip и его
        SHA-256, коммит версии и вывода самопроверки. Без тега и релиза.
    -Final — версия вида X.Y.Z. После ручной проверки: коммит, тег vX.Y.Z и GitHub Release с
        архивом. Репозиторий указывается ключом -Repo (по умолчанию публичный zhelezocheck).

    Общие шаги: чистое дерево, тесты, ruff, pyright → версия → поиск секретов → сборка
    (build.ps1 с самопроверкой) и check_no_traces.ps1 → проверка папки программы → архив и SHA-256.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\release.ps1 -Version 2.0.0-rc1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\release.ps1 -Version 2.0.0 -Final
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$Candidate,
    [switch]$Final,
    [string]$Repo = 'BagroDeRose/zhelezocheck'
)

if ($Candidate -and $Final) { throw 'Укажите один режим: -Candidate или -Final.' }
if ($Final) {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') {
        throw 'Финальный выпуск — версия вида 2.0.0 (без -rcN).'
    }
} elseif ($Version -notmatch '^\d+\.\d+\.\d+-rc[1-9]\d*$') {
    throw 'Кандидат — версия вида 2.0.0-rc1.'
}

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Tag = "v$Version"
$ReleaseDir = if ($Final) { Join-Path $Root 'release' } else { Join-Path $Root 'release\candidates' }
$Archive = Join-Path $ReleaseDir "ЖелезоЧек-$Tag.zip"

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What — ошибка (код $LASTEXITCODE)" }
}

Write-Step '1. Чистое рабочее дерево и проверки'
if (git status --porcelain) { throw 'Есть незакоммиченные изменения — сначала закоммитьте их.' }
if ($Final -and (git tag --list $Tag)) { throw "Тег $Tag уже есть." }
Invoke-Checked 'pytest' { & $Python -m pytest -q }
Invoke-Checked 'ruff' { & (Join-Path $Root '.venv\Scripts\ruff.exe') check . }
Invoke-Checked 'ruff format' { & (Join-Path $Root '.venv\Scripts\ruff.exe') format --check . }
Invoke-Checked 'pyright' { & (Join-Path $Root '.venv\Scripts\pyright.exe') }

Write-Step '2. Версия'
Invoke-Checked 'prepare' { & $Python scripts\release_tools.py prepare $Version }

Write-Step '3. Поиск секретов'
Invoke-Checked 'scan_secrets' { & $Python scripts\scan_secrets.py . }

Write-Step '4. Сборка, самопроверка и проверка «без следов»'
& powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
if ($LASTEXITCODE -ne 0) { throw 'Сборка не удалась' }
& powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_no_traces.ps1
if ($LASTEXITCODE -ne 0) { throw 'Проверка «без следов» не прошла' }

Write-Step '5. Папка программы без секретов и лишних файлов'
Invoke-Checked 'check-dist' { & $Python scripts\release_tools.py check-dist }

Write-Step '6. Архив и SHA-256'
Invoke-Checked 'pack' { & $Python scripts\release_tools.py pack $Version }
$Sha = (Get-Content -LiteralPath "$Archive.sha256" -Encoding UTF8).Split(' ')[0]

if (-not $Final) {
    Write-Step '7. Кандидат: коммит версии и вывода самопроверки (без тега и релиза)'
    git add pyproject.toml hwcheck\__init__.py "docs\qa\smoke_$Version*"
    git commit -m "Кандидат $Tag (без тега и релиза)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    if ($LASTEXITCODE -ne 0) { throw 'Коммит не удался' }
    Write-Step "Готово: кандидат $Archive, SHA-256 $Sha."
    exit 0
}

Write-Step '7. Финальный выпуск: коммит, тег, push, релиз'
git add pyproject.toml hwcheck\__init__.py "docs\qa\smoke_$Version*"
git commit -m "Выпуск $Tag" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
if ($LASTEXITCODE -ne 0) { throw 'Коммит не удался' }
git tag -a $Tag -m "ЖелезоЧек $Tag"
Invoke-Checked 'scan_secrets перед push' { & $Python scripts\scan_secrets.py . }
Invoke-Checked 'git push' { git push origin HEAD }
Invoke-Checked 'git push tag' { git push origin $Tag }

$Notes = Join-Path $Root '.tmp\release_notes.md'
Invoke-Checked 'notes' { & $Python scripts\release_tools.py notes $Version $Notes }
Add-Content -LiteralPath $Notes -Encoding utf8 -Value "`nSHA-256 архива: $Sha"
Invoke-Checked 'gh release' {
    # GitHub удаляет кириллицу из имён вложений: загружаем копию с латинским именем.
    & $Python scripts\release_tools.py upload-copies $Version | Out-Null
    $Upload = Join-Path $Root "release\upload\ZhelezoChek-$Tag.zip"
    gh release create $Tag "$Upload#ЖелезоЧек-$Tag.zip" "$Upload.sha256#ЖелезоЧек-$Tag.zip.sha256" --repo $Repo --title "ЖелезоЧек $Tag" --notes-file $Notes
}
Write-Step "Готово: $Tag, SHA-256 $Sha"
