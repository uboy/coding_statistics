@echo off
setlocal
echo Building stats_main standalone executable with PyInstaller...
if not exist "%~dp0venv" (
    echo [INFO] No local venv detected. Ensure pyinstaller is available in PATH.
)
pyinstaller --onefile --name stats_tool --add-data "templates;templates" stats_main.py
echo Build finished. Executable is available in the dist\ directory.
endlocal

