@echo off
rem Compare original and upscaled textures of a pack build and mark them.
rem   texcompare.cmd [pack work folder]   (default: the v2 build of The Last Guardian)
set WORK=%~1
if "%WORK%"=="" set WORK=F:\emulation\texturepacks\tlg\v2.work
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0texcompare.py" "F:\emulation\ps4\shadps4games\CUSA03745" "%WORK%"
