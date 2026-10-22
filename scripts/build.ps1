param([string]$Python = '', [string]$Destination = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run scripts\setup.ps1 first, or pass -Python.' }
if (-not $Destination) { $Destination = Join-Path $projectRoot 'dist' }
$Destination = [System.IO.Path]::GetFullPath($Destination)
$target = Join-Path $Destination 'ImageFlow'
if (Test-Path -LiteralPath $target) {
    throw "Output already exists: $target. Choose a fresh -Destination to preserve existing portable settings."
}
$originalBuildPath = $env:PATH
try {
    # Do not let unrelated SDKs / image utilities on PATH supply Qt's system DLLs.
    $env:PATH = (Split-Path -Parent $Python) + ';' + (Join-Path $env:WINDIR 'System32') + ';' + $env:WINDIR
    & $Python -m PyInstaller --clean --distpath $Destination ImageFlow.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
} finally {
    $env:PATH = $originalBuildPath
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination $target
Copy-Item -LiteralPath (Join-Path $projectRoot 'THIRD_PARTY_NOTICES.md') -Destination $target
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $target
$licenses = Join-Path $target 'licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
& $Python (Join-Path $projectRoot 'scripts\collect_licenses.py') $licenses
if ($LASTEXITCODE -ne 0) { throw 'Collecting third-party license texts failed.' }
& $Python (Join-Path $projectRoot 'scripts\check_binary_dependencies.py') $target
if ($LASTEXITCODE -ne 0) { throw 'Qt DLL loading preflight failed. Do not distribute this build.' }
Write-Host "Portable build ready: $target\ImageFlow.exe"
Write-Host 'Distribute the entire ImageFlow folder. FFmpeg is not bundled.'
