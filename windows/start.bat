@echo off
chcp 65001 >nul
title NapCat-M Stack
cd /d "%~dp0"

echo [1/2] 启动 NapCat-M Shell（QQ 注入端）...
start "NapCat-M Shell" "%~dp0run-napcat.bat"

echo [2/2] 启动 AstrBot（LLM Bot 框架）...
start "AstrBot" "%~dp0run-astrbot.bat"

echo.
echo 两端已启动：
echo   NapCat-M WebUI : http://127.0.0.1:6099   （QQ 扫码登录 / 网络配置）
echo   AstrBot WebUI  : http://127.0.0.1:6185   （填 API Key / 人格 / 插件）
echo.
echo 首次使用请看仓库 README.md 的「五步上手」。
echo 关闭本窗口不影响两端运行；要停止请在两个子窗口里 Ctrl+C。
pause
