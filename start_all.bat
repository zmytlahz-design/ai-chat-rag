@echo off
chcp 65001 >nul 2>&1
title AI 知识库对话系统 - 全量一键启动
setlocal

echo ============================================
echo   AI 知识库对话系统 - 全量一键启动
echo   (MCP Bridge + Docker 服务)
echo ============================================
echo.

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker 未运行，请先启动 Docker Desktop
    pause
    exit /b 1
)

if not exist ".env" (
    echo [提示] 未检测到 .env 文件，正在从模板创建...
    copy .env.example .env >nul
    echo [警告] 请先编辑 .env 文件，填写 API Key 等必要配置！
    notepad .env
    pause
    exit /b 0
)

set "APP_PORT="
set "LEGACY_PORT="
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if /i "%%~A"=="FRONTEND_PORT" set "APP_PORT=%%B"
    if /i "%%~A"=="NGINX_PORT" set "LEGACY_PORT=%%B"
)
if defined APP_PORT goto port_ok
if defined LEGACY_PORT set "APP_PORT=%LEGACY_PORT%"
if not defined APP_PORT set "APP_PORT=80"
:port_ok

echo [1/4] 启动 MCP Bridge...
start "MCP Bridge" cmd /k "cd /d %~dp0 && call start_mcp_bridge.bat"
timeout /t 2 /nobreak >nul

echo [2/4] 启动 Docker 服务...
docker compose up -d
if %errorlevel% neq 0 (
    echo [提示] 启动失败，尝试构建后启动...
    docker compose up -d --build
)
if %errorlevel% neq 0 (
    echo [错误] Docker 服务启动失败，请检查日志
    pause
    exit /b 1
)

set "COMPOSE_PORT_RAW="
for /f "delims=" %%P in ('docker compose port frontend 80 2^>nul') do set "COMPOSE_PORT_RAW=%%P"
if defined COMPOSE_PORT_RAW (
    for /f "tokens=2 delims=:" %%Q in ("%COMPOSE_PORT_RAW%") do set "APP_PORT=%%Q"
)

echo [3/4] 健康检查...
timeout /t 5 /nobreak >nul
docker exec rag_frontend wget -qO- http://127.0.0.1:80/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 前端健康检查通过
) else (
    echo [提示] 前端仍在启动中，稍后刷新浏览器
)

curl --silent --fail http://127.0.0.1:9000/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] MCP Bridge 健康检查通过
) else (
    echo [提示] MCP Bridge 可能尚未完全启动（窗口会继续尝试启动）
)

echo [4/4] 启动完成！
echo.
echo   前端界面:  http://localhost:%APP_PORT%
echo   API 文档:  http://localhost:%APP_PORT%/docs
echo   MCP 健康:  http://localhost:9000/health
echo.
echo   查看日志:  docker compose logs -f
echo   停止服务:  docker compose down
echo ============================================
echo.

start http://localhost:%APP_PORT%
pause

