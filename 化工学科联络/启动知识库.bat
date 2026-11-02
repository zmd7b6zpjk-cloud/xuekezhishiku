@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   化工学科联络 · 本地知识库
echo   正在启动，稍后浏览器会自动打开 http://127.0.0.1:8765/
echo.
python -c "import sys" >nul 2>nul
if errorlevel 1 (
    py -3 kb.py serve
) else (
    python kb.py serve
)
if errorlevel 1 pause
