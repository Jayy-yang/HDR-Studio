@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PIP_CACHE_DIR=%~dp0.pipcache"
set "LOG=%~dp0install.log"
set "BASEPY="
set "RUNTIME="
title HDR Studio Launcher

rem ---------- request administrator privileges ----------
if defined HDRSTUDIO_ELEVATED goto admin_ready
fltmc >nul 2>&1
if not errorlevel 1 goto admin_ready
echo Requesting administrator privileges...
echo A Windows UAC prompt will appear.
set "HDRSTUDIO_ELEVATED=1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
if errorlevel 1 (
    echo.
    echo Administrator privileges were not granted. The application needs them to start.
    pause
)
exit /b

:admin_ready

echo.
echo ==========================================================
echo   HDR Studio - Starting
echo   Folder: %~dp0
echo ==========================================================
echo.

rem ---------- 1. reuse an existing virtual environment ----------
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import cv2, PIL, numpy, tkinter" >nul 2>nul
    if not errorlevel 1 (
        set "RUNTIME=pythonw"
        goto launch
    )
    echo [1/3] Environment found. Installing missing packages...
    if not exist ".venv\Scripts\pip.exe" (
        ".venv\Scripts\python.exe" -m ensurepip >>"%LOG%" 2>&1
    )
    if not exist ".venv\Scripts\pip.exe" goto fail_venv
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --prefer-binary numpy Pillow opencv-python >"%LOG%" 2>&1
    if errorlevel 1 goto fail_install
    goto verify
)

rem ---------- 2. find Python and create a fresh venv ----------
echo [1/3] Creating virtual environment...

if exist "%LocalAppData%\Programs\Python\Python314\python.exe" set "BASEPY=%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined BASEPY (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python31*") do set "BASEPY=%%D\python.exe"
)
if not defined BASEPY (
    py -3 -c "import sys" >nul 2>nul && set "BASEPY=py -3"
)
if not defined BASEPY (
    python -c "import sys" >nul 2>nul && set "BASEPY=python"
)
if not defined BASEPY goto fail_nopython

%BASEPY% -m venv .venv >>"%LOG%" 2>&1
if not exist ".venv\Scripts\python.exe" goto fail_venv
if not exist ".venv\Scripts\pip.exe" (
    .venv\Scripts\python.exe -m ensurepip >>"%LOG%" 2>&1
)
if not exist ".venv\Scripts\pip.exe" goto fail_venv

echo [2/3] Installing NumPy, Pillow and OpenCV...
echo       First run may take 1-3 minutes. Please keep the network on.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --prefer-binary numpy Pillow opencv-python >>"%LOG%" 2>&1
if errorlevel 1 goto fail_install

:verify
echo [3/3] Verifying installation...
".venv\Scripts\python.exe" -c "import cv2, PIL, numpy, tkinter" >"%LOG%" 2>&1
if errorlevel 1 goto fail_verify
set "RUNTIME=pythonw"

:launch
echo.
echo Starting HDR Studio...
if exist ".venv\Scripts\%RUNTIME%.exe" (
    start "" /d "%~dp0" ".venv\Scripts\%RUNTIME%.exe" "%~dp0app.py"
) else (
    start "" /d "%~dp0" ".venv\Scripts\python.exe" "%~dp0app.py"
)
exit /b 0

rem ---------- errors ----------
:fail_nopython
echo.
echo [ERROR] Python 3.10+ was not found.
echo         Install it from https://www.python.org/downloads/
echo         Enable "Add Python to PATH", then run this file again.
echo.
pause
exit /b 1

:fail_venv
echo.
echo [ERROR] Cannot create .venv.
echo         Log: %LOG%
echo         Move the project to a writable folder and try again.
echo.
pause
exit /b 1

:fail_install
echo.
echo [ERROR] Package installation failed.
echo         Log: %LOG%
echo         Check the network / proxy / firewall, then try:
echo           .venv\Scripts\python.exe -m pip install numpy Pillow opencv-python
echo         In mainland China you can use a mirror:
echo           .venv\Scripts\python.exe -m pip install numpy Pillow opencv-python -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:fail_verify
echo.
echo [ERROR] Packages are installed but cannot be imported.
echo         Log: %LOG%
echo.
type "%LOG%"
echo.
pause
exit /b 1
