@echo off
title AstrBot
cd /d "%~dp0AstrBot"
if not exist "venv\Scripts\python.exe" (
    echo [!] 未找到 AstrBot 虚拟环境：请先运行 install.ps1 完成 AstrBot 部署。
    pause
    exit /b 1
)
venv\Scripts\python.exe main.py
pause
