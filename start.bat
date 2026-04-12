@echo off
setlocal EnableExtensions
title AI Chat RAG - Start

echo This script now calls start_all.bat.
echo Use:
echo   start.bat           (no auto-open browser)
echo   start.bat --open    (open browser automatically)
echo.
call "%~dp0start_all.bat" %*
