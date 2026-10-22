param([string]$FFmpeg = '', [string]$FFprobe = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if ($FFmpeg) { $env:IMAGEFLOW_FFMPEG = $FFmpeg }
if ($FFprobe) { $env:IMAGEFLOW_FFPROBE = $FFprobe }
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
& '.\.venv\Scripts\python.exe' -m pytest -q -ra --junitxml=artifacts/test-results.xml
exit $LASTEXITCODE
