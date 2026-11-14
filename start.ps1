$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = '.\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath '.venv312\Scripts\python.exe') {
    $pythonPath = '.\.venv312\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer, then retry.' }
}
& $pythonPath -c 'import fastapi, uvicorn, multipart, faster_whisper, httpx'
if ($LASTEXITCODE -ne 0) {
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See the error above.' }
}
Write-Host 'Open http://127.0.0.1:8765 in your browser. Keep this window open.'
& $pythonPath app.py
