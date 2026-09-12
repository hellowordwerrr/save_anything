@echo off
rem Build the single-exe app (PyInstaller is a build-time-only dependency).
cd /d "%~dp0"
python -m pip install pyinstaller || goto :fail
if not exist icon.ico powershell -NoProfile -ExecutionPolicy Bypass -File make_icon.ps1
pyinstaller shiyi.spec || goto :fail
echo.
echo Build OK. Output: dist\
goto :eof
:fail
echo Build FAILED. See messages above.
exit /b 1
