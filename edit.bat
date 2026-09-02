@echo off
setlocal enabledelayedexpansion

REM 设置项目根目录（当前目录）
set "PROJECT_DIR=%~dp0"
set "PARAM_FILE=%PROJECT_DIR%parameters\video.txt"

echo ============================================
echo   视频生成参数快速设置工具
echo ============================================
echo.

REM 检查参数目录是否存在
if not exist "%PROJECT_DIR%parameters" mkdir "%PROJECT_DIR%parameters"

REM ---------- 选择分辨率 ----------
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

REM ---------- 输入视频时长 ----------
echo.
set /p SECONDS=请输入视频时长（秒，建议 5-30），默认 5: 
if "%SECONDS%"=="" set "SECONDS=5"

REM ---------- 写入参数文件 ----------
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