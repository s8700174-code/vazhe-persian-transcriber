@echo off
cd /d "%~dp0"
set "V2T_PY=.venv312\Scripts\python.exe"
if not exist "%V2T_PY%" set "V2T_PY=.venv\Scripts\python.exe"
"%V2T_PY%" -c "import torch, transformers, accelerate, safetensors"
if not errorlevel 1 goto prepare
"%V2T_PY%" -m pip install -r requirements-persian.txt --timeout 20 --retries 1
if errorlevel 1 goto done
:prepare
"%V2T_PY%" prepare_persian.py %*
:done
pause
