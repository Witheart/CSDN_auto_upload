@echo off
:: 设置控制台为 UTF-8 编码，防止中文乱码
chcp 65001 >nul

echo =========================================
echo       CSDN 自动图文发布工具启动中...
echo =========================================

:: 调用你的虚拟环境中的 Python 执行脚本，并传入右键选中的文件路径 (%~1)
"F:\0000_TOOL\CSDN_auto_upload\.venv\Scripts\python.exe" "F:\0000_TOOL\CSDN_auto_upload\csdn_auto_upload.py" "%~1"

echo.
echo =========================================
echo       执行完毕，请检查上面的日志输出
echo =========================================
pause