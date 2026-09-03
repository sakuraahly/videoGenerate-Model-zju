@echo off
chcp 65001 >nul
rem AI 创意桥：一段创意 -> 各工作流提示词（需 config\llm.json）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\shell\ai_prompts.ps1"
exit /b %errorlevel%