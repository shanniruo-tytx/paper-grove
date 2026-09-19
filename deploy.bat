@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Windows 双击一键部署：装依赖 -> 构建 -> 启动站点
rem 传参透传给 deploy.py，例如 deploy.bat --no-deps

where python >nul 2>nul
if %errorlevel%==0 (
  python deploy.py %*
  goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
  py deploy.py %*
  goto :end
)

echo [ERROR] 未在 PATH 中找到 python / py，请先安装 Python 3.8+ 并勾选 Add to PATH。

:end
echo.
pause
