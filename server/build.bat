@echo off
echo ================================================
echo   阿里云DSW自动点击器 - 打包工具
echo ================================================
echo.

cd /d "%~dp0"

echo 正在安装依赖...
pip install pyinstaller playwright schedule -q

echo.
echo 正在安装浏览器驱动...
python -m playwright install chromium

echo.
echo 正在打包，请稍候...
pyinstaller --onefile --windowed --name "阿里云DSW自动点击器" --icon=NONE auto_click_gui.py

echo.
echo ================================================
echo   打包完成！
echo ================================================
echo.
echo 安装包位置: dist\阿里云DSW自动点击器.exe
echo.
echo 使用方法:
echo 1. 先启动Edge浏览器并启用远程调试:
echo    msedge --remote-debugging-port=9222
echo.
echo 2. 打开目标网页
echo.
echo 3. 运行自动点击器，点击"开始"即可
echo.
pause
