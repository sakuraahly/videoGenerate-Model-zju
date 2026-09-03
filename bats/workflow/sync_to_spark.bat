@echo off
chcp 65001 >nul
rem 同步整个项目到 spark（不含 .git，遵守传输约定；用法：本工具同 git 推送配合）
python "%~dp0..\..\runs\sync_to_spark.py" %*
exit /b %errorlevel%
