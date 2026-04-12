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

set "AUTO_OPEN_BROWSER=0"
if /i "%~1"=="--open" set "AUTO_OPEN_BROWSER=1"

set "APP_PORT="
set "PG_USER="
set "PG_DB="
set "PG_PASSWORD="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if /i "%%~A"=="FRONTEND_PORT" set "APP_PORT=%%~B"
  if /i "%%~A"=="NGINX_PORT" if not defined APP_PORT set "APP_PORT=%%~B"
  if /i "%%~A"=="POSTGRES_USER" set "PG_USER=%%~B"
  if /i "%%~A"=="POSTGRES_DB" set "PG_DB=%%~B"
  if /i "%%~A"=="POSTGRES_PASSWORD" set "PG_PASSWORD=%%~B"
)
if not defined APP_PORT set "APP_PORT=80"
if not defined PG_USER set "PG_USER=rag_user"
if not defined PG_DB set "PG_DB=rag_db"

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

echo [3/4] Waiting for backend health ...
set /a "HEALTH_TRIES=0"
:wait_backend
set /a "HEALTH_TRIES+=1"
docker exec rag_frontend wget -qO- http://backend:8000/health >nul 2>&1
if errorlevel 1 (
  if %HEALTH_TRIES% GEQ 120 (
    echo [ERROR] Backend still not healthy after retries.
    pause
    exit /b 1
  )
  if %HEALTH_TRIES% GEQ 60 (
    echo [WARN] Backend health check timeout. Showing recent backend logs:
    docker compose logs --tail 80 backend
    echo [INFO] Trying to sync postgres password from .env ...
    if defined PG_PASSWORD (
      docker exec rag_postgres psql -U "%PG_USER%" -d "%PG_DB%" -c "ALTER USER \"%PG_USER%\" WITH PASSWORD '%PG_PASSWORD%';" >nul 2>&1
      if errorlevel 1 (
        echo [WARN] Password sync failed. Please check POSTGRES_PASSWORD in .env.
      ) else (
        echo [OK] Password synced. Restarting backend ...
        docker compose restart backend >nul 2>&1
        set /a "HEALTH_TRIES=0"
        timeout /t 2 /nobreak >nul
        goto wait_backend
      )
    ) else (
      echo [WARN] POSTGRES_PASSWORD is empty in .env.
    )
  )
  timeout /t 2 /nobreak >nul
  goto wait_backend
)

echo [4/4] Ready.
echo UI:   http://localhost:%APP_PORT%
echo Docs: http://localhost:%APP_PORT%/docs
echo MCP:  http://localhost:9000/health
echo.
echo Logs: docker compose logs -f
echo Stop: docker compose down
echo.
if "%AUTO_OPEN_BROWSER%"=="1" (
  start "" "http://localhost:%APP_PORT%"
) else (
  echo Browser auto-open is OFF. Run:
  echo   start "" "http://localhost:%APP_PORT%"
  echo or use:
  echo   start_all.bat --open
)
pause
