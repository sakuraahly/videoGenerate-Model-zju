@echo off
chcp 65001 >nul
rem 两个文件夹自动化合并开关（bats\workflow\autosync.bat -> runs\sync_auto.py）
set ROOT=%~dp0..\..
:menu
echo.
echo   ============================================================
echo       两个文件夹自动化合并
echo   ============================================================
echo    [1] 开启自动合并（周期 180s，后台 watch）
echo    [2] 关闭自动合并
echo    [3] 立即合并一次
echo    [4] 查看状态/最近日志
echo    [0] 返回
echo.
set /p CH=请选择 (0-4): 
if "%CH%"=="1" python "%ROOT%\runs\sync_auto.py" enable --daemon --interval 180
if "%CH%"=="2" python "%ROOT%\runs\sync_auto.py" disable
if "%CH%"=="3" python "%ROOT%\runs\sync_auto.py" once
if "%CH%"=="4" python "%ROOT%\runs\sync_auto.py" status
if "%CH%"=="0" exit /b 0
echo.
pause
goto menu