@echo off
rem UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
rem Starts UBE Tailor with the Python that ships with it (python\pythonw.exe), or with an installed Python.
rem -s: ignore the user's own Python packages, -E: ignore PYTHON* settings (the tool runs the same everywhere)
cd /d "%~dp0"
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" -s -E "%~dp0tailor_gui.py"
    exit /b 0
)
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw -s -E "%~dp0tailor_gui.py"
    exit /b 0
)
echo Python was not found. Use the full UBE Tailor download (it has Python inside),
echo or install Python 3 from python.org and run:  py -m pip install numpy scipy
pause
exit /b 1
