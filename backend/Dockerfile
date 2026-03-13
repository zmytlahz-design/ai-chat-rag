# ==================================================
# 后端 Dockerfile
# 基于 Python 3.11 slim 镜像构建
# ==================================================

# 第一阶段：使用官方 Python 3.11 精简镜像作为基础
FROM python:3.11-slim

# 设置环境变量
# PYTHONDONTWRITEBYTECODE=1 : 不生成 .pyc 缓存文件，减小镜像体积
# PYTHONUNBUFFERED=1        : 关闭输出缓冲，日志实时打印到终端
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 设置容器内工作目录
WORKDIR /app

# 安装系统级依赖
# build-essential : 编译 C 扩展（asyncpg 等需要）
# libpq-dev       : PostgreSQL 客户端头文件（psycopg 依赖）
# && rm -rf ...   : 清理 apt 缓存，减小镜像体积
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 先单独复制 requirements.txt
# 利用 Docker 层缓存机制：只要依赖不变，这一层就不会重新构建
COPY requirements.txt .

# 安装 Python 依赖
# --no-cache-dir : 不缓存安装包，减小镜像体积
# --upgrade pip  : 先升级 pip
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 将项目所有代码复制到容器工作目录
COPY . .

# 声明容器对外暴露的端口（仅作文档用，实际端口映射在 docker-compose 中配置）
EXPOSE 8000

# 容器启动命令（生产模式）
# --host 0.0.0.0  : 监听所有网络接口（容器内必须这样设置）
# --port 8000     : 监听端口
# --workers 2     : 启动 2 个 worker 进程（根据 CPU 核心数调整）
# --loop uvloop   : 使用高性能事件循环（需安装 uvloop，已在 requirements.txt 中）
# 注意：使用 --workers > 1 时不能用 --reload（多进程不支持热重载）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
