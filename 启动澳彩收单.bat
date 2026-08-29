@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import flask" 2>nul
if errorlevel 1 (
  echo 正在安装 Flask...
  python -m pip install flask
)
echo 正在启动澳彩收单独立版...
python aocai_app.py
pause
