#!/usr/bin/env bash
set -euo pipefail

echo "Building stats_main standalone executable with PyInstaller..."
if [[ ! -d "venv" ]]; then
  echo "[INFO] No local venv detected. Ensure pyinstaller is available in PATH."
fi
pyinstaller --onefile --name stats_tool --add-data "templates:templates" stats_main.py
echo "Build finished. Executable is available in the dist/ directory."

