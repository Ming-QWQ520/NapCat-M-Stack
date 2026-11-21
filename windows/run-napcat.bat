@echo off
title NapCat-M Shell
cd /d "%~dp0"
set "NAPCAT_BAT="
for /r "%~dp0napcat-shell" %%f in (napcat.bat) do set "NAPCAT_BAT=%%f"
if "%NAPCAT_BAT%"=="" (
    echo [!] 未找到 napcat.bat：请先运行 install.ps1 安装 NapCat-M Shell，
    echo     并执行其中的 NapCatInstaller.exe 完成对本机 QQ 的注入。
    pause
    exit /b 1
)
call "%NAPCAT_BAT%"
pause
