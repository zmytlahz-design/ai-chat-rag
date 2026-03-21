@echo off
chcp 65001 >nul 2>&1
title AI 知识库对话系统 - 一键启动

echo ============================================
echo   AI 知识库对话系统 - 一键启动脚本
echo ============================================
echo.

:: 检查 Docker 是否运行
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker 未运行，请先启动 Docker Desktop
    pause
    exit /b 1
)

:: 检查 .env 文件
if not exist ".env" (
    echo [提示] 未检测到 .env 文件，正在从模板创建...
    copy .env.example .env >nul
    echo [警告] 请先编辑 .env 文件，填写 API Key 等必要配置！
    echo         至少需要填写：POSTGRES_PASSWORD / LLM_API_KEY / EMBEDDING_API_KEY
    notepad .env
    pause
    exit /b 0
)

echo [1/3] 正在启动服务...
echo.
docker compose up -d
if %errorlevel% neq 0 (
    echo.
    echo [提示] 镜像不存在或启动失败，正在构建并启动（首次运行或依赖变更时会执行）...
    echo.
    docker compose up -d --build
)
if %errorlevel% neq 0 (
    echo.
    echo [错误] 启动失败，请检查上方日志
    pause
    exit /b 1
)

echo.
echo [2/3] 等待服务就绪...
timeout /t 8 /nobreak >nul

:: 检查后端是否正常（容器内 nginx 监听 80，宿主机访问用 NGINX_PORT 如 3080）
docker exec rag_nginx wget -qO- http://127.0.0.1:80/api/v1/knowledge-bases >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 后端 API 正常
) else (
    echo [提示] 后端仍在启动中，请稍等几秒后刷新页面
)

echo.
echo [3/3] 启动完成！
echo ============================================
echo.
echo   前端界面:  http://localhost:3080
echo   API 文档:  http://localhost:3080/api/v1/docs
echo.
echo   查看日志:  docker compose logs -f
echo   停止服务:  docker compose down
echo ============================================
echo.

:: 自动打开浏览器（端口与 .env 中 NGINX_PORT 一致）
start http://localhost:3080

pause
