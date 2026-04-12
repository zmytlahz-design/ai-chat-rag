@echo off
chcp 65001 >nul 2>&1
title AI 知识库对话系统 - 一键启动

echo ============================================
echo   AI 知识库对话系统 - 一键启动脚本
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
    echo         至少需要填写：POSTGRES_PASSWORD / LLM_API_KEY / EMBEDDING_API_KEY
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

echo [1/3] 正在启动服务...
docker compose up -d
if %errorlevel% neq 0 (
    echo.
    echo [提示] 镜像不存在或启动失败，正在构建并启动...
    docker compose up -d --build
)
if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请检查上方日志
    pause
    exit /b 1
)

set "COMPOSE_PORT_RAW="
for /f "delims=" %%P in ('docker compose port frontend 80 2^>nul') do set "COMPOSE_PORT_RAW=%%P"
if defined COMPOSE_PORT_RAW (
    for /f "tokens=2 delims=:" %%Q in ("%COMPOSE_PORT_RAW%") do set "APP_PORT=%%Q"
)

echo.
echo [2/3] 等待服务就绪...
timeout /t 5 /nobreak >nul
docker exec rag_frontend wget -qO- http://127.0.0.1:80/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 服务健康检查通过
) else (
    echo [提示] 服务仍在启动中，请稍等几秒后刷新页面
)

echo.
echo [3/3] 启动完成！
echo ============================================
echo.
echo   前端界面:  http://localhost:%APP_PORT%
echo   API 文档:  http://localhost:%APP_PORT%/docs
echo.
echo   查看日志:  docker compose logs -f
echo   停止服务:  docker compose down
echo ============================================
echo.

start http://localhost:%APP_PORT%
pause
