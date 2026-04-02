# ==================================================
# FastAPI 应用入口
# 负责：创建 app 实例、注册中间件、挂载路由、生命周期管理
# ==================================================

import logging
from contextlib import asynccontextmanager  # 用于定义异步上下文管理器（lifespan）

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # 跨域中间件

from config import settings      # 全局配置
from database import init_db  # 数据库初始化函数

# 导入所有路由模块
from routers import knowledge_base, document, chat, conversation

logger = logging.getLogger(__name__)

# --------------------------------------------------
# 1. 应用生命周期管理（lifespan）
# --------------------------------------------------
# lifespan 是 FastAPI 0.93+ 推荐的启动/关闭钩子写法，
# 替代了旧版的 @app.on_event("startup") / @app.on_event("shutdown")
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期上下文管理器。
    yield 之前的代码在应用启动时执行（startup）。
    yield 之后的代码在应用关闭时执行（shutdown）。
    """
    # ---- 启动时执行 ----
    logger.info("%s v%s 正在启动...", settings.APP_NAME, settings.APP_VERSION)

    # 初始化数据库：创建所有表（如果不存在）
    await init_db()
    logger.info("数据库表初始化完成")

    yield  # 应用正常运行期间停在这里

    # ---- 关闭时执行 ----
    logger.info("应用正在关闭，清理资源...")


# --------------------------------------------------
# 2. 创建 FastAPI 应用实例
# --------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于 RAG 技术的 AI 多轮对话知识库系统",
    # 只在调试模式下显示文档（生产环境可关闭）
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,  # 绑定生命周期管理器
)


# --------------------------------------------------
# 3. 注册 CORS 中间件
# --------------------------------------------------
# 必须在路由注册之前添加，否则预检请求（OPTIONS）会返回 404
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # 允许的前端地址列表
    allow_credentials=True,               # 允许携带 Cookie
    allow_methods=["*"],                  # 允许所有 HTTP 方法（GET/POST/PUT/DELETE 等）
    allow_headers=["*"],                  # 允许所有请求头
)


# --------------------------------------------------
# 4. 注册路由
# --------------------------------------------------
# prefix 是路由前缀，tags 用于在 Swagger 文档中分组
app.include_router(
    knowledge_base.router,
    prefix="/api/v1/knowledge-bases",
    tags=["知识库管理"],
)
app.include_router(
    document.router,
    prefix="/api/v1/documents",
    tags=["文档管理"],
)
app.include_router(
    chat.router,
    prefix="/api/v1/chat",
    tags=["对话"],
)
app.include_router(
    conversation.router,
    prefix="/api/v1/conversations",
    tags=["对话历史"],
)


# --------------------------------------------------
# 5. 根路由（健康检查）
# --------------------------------------------------
@app.get("/", tags=["健康检查"])
async def root():
    """根路由，用于检查服务是否正常运行"""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/health", tags=["健康检查"])
async def health_check():
    """健康检查接口，docker-compose healthcheck 可以调用此接口"""
    return {"status": "healthy"}
