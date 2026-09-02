@echo off
rem ============================================================
rem  Pipeline / multi-workflow setup tool
rem  流水线 / 多工作流（阶段、模板、默认生成方式）设置入口
rem ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0shell\pipeline_setup.ps1"
exit /b %errorlevel%
