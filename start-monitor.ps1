$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Мониторинг регулятора — запущен'
Set-Location $PSScriptRoot
$env:MONITOR_DATA = Join-Path $PSScriptRoot 'runtime\local-data'
$env:B24_SECRET_FILE = Join-Path $PSScriptRoot 'secrets.txt'
$env:MONITOR_BIND = '127.0.0.1'
$env:MONITOR_PORT = '8787'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:OCR_ENABLED = 'yes'
$ocrDirectory = 'C:\projects\cbr-regulatory-monitor-tools\tesseract'
$popplerDirectory = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin'
$env:PATH = $ocrDirectory + ';' + $popplerDirectory + ';' + $env:PATH
Write-Host 'Мониторинг регулятора' -ForegroundColor Cyan
Write-Host 'Сайт: http://localhost:8787'
Write-Host 'Остановка: Ctrl+C или кнопка на сайте. Данные сохраняются.'
python local_server.py
$Host.UI.RawUI.WindowTitle = 'Мониторинг регулятора — остановлен'
