@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
rem 修改生成参数（bats\config\edit.bat）
set "ROOT=%~dp0..\.."
set "PARAM_FILE=%ROOT%\parameters\video.txt"

echo ============================================
echo   视频生成参数快速设置工具
echo ============================================
echo.
if not exist "%ROOT%\parameters" mkdir "%ROOT%\parameters"

echo 请选择视频分辨率（输入数字后回车）：
echo 1. 360p  (608x352)
echo 2. 480p  (864x480)
echo 3. 540p  (960x544)
echo 4. 720p  (1280x736)
echo 5. 768p  (1344x768)
echo.
set /p RES_CHOICE=请输入选项 (1-5)，默认 480p: 

set "RESOLUTION=480p"
if "%RES_CHOICE%"=="1" set "RESOLUTION=360p"
if "%RES_CHOICE%"=="2" set "RESOLUTION=480p"
if "%RES_CHOICE%"=="3" set "RESOLUTION=540p"
if "%RES_CHOICE%"=="4" set "RESOLUTION=720p"
if "%RES_CHOICE%"=="5" set "RESOLUTION=768p"

echo.
set /p SECONDS=请输入视频时长（秒，建议 5-30），默认 5: 
if "%SECONDS%"=="" set "SECONDS=5"

echo.
echo 正在更新参数文件...
(
    echo # 视频生成参数配置文件
    echo resolution=%RESOLUTION%
    echo seconds=%SECONDS%
) > "%PARAM_FILE%"

echo.
echo 参数已保存至：
echo %PARAM_FILE%
echo.
echo 当前参数：
echo  分辨率: %RESOLUTION%
echo  时长: %SECONDS% 秒
echo.
pause

endlocal