@echo off
rem Runs texpack.py in the environment setup.ps1 made. Example:
rem   texpack make "D:\Games\CUSA03745" "D:\Packs\UltraSharp 4x"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Run setup.ps1 first: powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0texpack.py" %*
