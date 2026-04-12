@echo off
setlocal EnableExtensions
title AI Chat RAG - Full Start

echo ============================================
echo   AI Chat RAG - Full Start
echo   (MCP Bridge + Docker Services)
echo ============================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker is not running. Start Docker Desktop first.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [INFO] .env not found, creating from .env.example ...
  copy .env.example .env >nul
  echo [INFO] Please fill required keys in .env, then rerun.
  notepad .env
  pause
  exit /b 0
)

set "APP_PORT="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if /i "%%~A"=="FRONTEND_PORT" set "APP_PORT=%%~B"
  if /i "%%~A"=="NGINX_PORT" if not defined APP_PORT set "APP_PORT=%%~B"
)
if not defined APP_PORT set "APP_PORT=80"

echo [1/4] Starting MCP bridge in a new window ...
start "MCP Bridge" cmd /k "cd /d %~dp0 && call start_mcp_bridge.bat"

echo [2/4] Starting Docker services ...
docker compose up -d
if errorlevel 1 docker compose up -d --build
if errorlevel 1 (
  echo [ERROR] Failed to start Docker services.
  pause
  exit /b 1
)

echo [3/4] Waiting for services ...
timeout /t 5 /nobreak >nul

echo [4/4] Ready.
echo UI:   http://localhost:%APP_PORT%
echo Docs: http://localhost:%APP_PORT%/docs
echo MCP:  http://localhost:9000/health
echo.
echo Logs: docker compose logs -f
echo Stop: docker compose down
echo.
start http://localhost:%APP_PORT%
pause
