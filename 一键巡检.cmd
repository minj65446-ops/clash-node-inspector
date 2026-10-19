@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ============================================
echo   Clash Node Inspector - 一键巡检
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python 命令。
  echo 请先安装 Python 3.8+ 并勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 2
)

python daily_inspect.py %*
set CODE=%ERRORLEVEL%

echo.
if "%CODE%"=="0" (
  echo [完成] 巡检成功，报告在 reports\ 目录下。
) else if "%CODE%"=="3" (
  echo [告警] 存活率低于阈值，请查看 reports 下的报告。
) else (
  echo [失败] 巡检出错，退出码 %CODE%。
)

echo.
pause
exit /b %CODE%
