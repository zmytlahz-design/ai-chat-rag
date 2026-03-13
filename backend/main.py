# ==================================================
# FastAPI 应用入口
# 负责：创建 app 实例、注册中间件、挂载路由、生命周期管理
# ==================================================

import json
import os
import re
import time
from contextlib import asynccontextmanager  # 用于定义异步上下文管理器（lifespan）

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # 跨域中间件

from config import settings      # 全局配置
from database import init_db, AsyncSessionLocal  # 数据库初始化函数
from services.redis_service import redis_service  # Redis 服务（用于关闭连接）

# 导入所有路由模块
from routers import knowledge_base, document, chat, conversation

# #region agent log
def _debug_log(message: str, data: dict, hypothesis_id: str, run_id: str = ""):
    try:
        log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "debug-4ad711.log"))
        payload = {"sessionId": "4ad711", "location": "main.py", "message": message, "data": data, "timestamp": int(time.time() * 1000), "hypothesisId": hypothesis_id}
        if run_id:
            payload["runId"] = run_id
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #endregion


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
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 正在启动...")

    # 初始化数据库：创建所有表（如果不存在）
    await init_db()
    print("✅ 数据库表初始化完成")

    # #region agent log
    try:
        from sqlalchemy import select, func
        from models.knowledge_base import KnowledgeBase
        async with AsyncSessionLocal() as sess:
            r = await sess.execute(select(func.count(KnowledgeBase.id)))
            kb_count = r.scalar() or 0
        db_masked = re.sub(r"://[^@]+@", "://***@", settings.DATABASE_URL)
        _debug_log("startup kb count", {"count": kb_count, "database_masked": db_masked}, "H2,H4,H5")
    except Exception as e:
        _debug_log("startup kb count error", {"error": str(e)}, "H4")
    # #endregion

    yield  # 应用正常运行期间停在这里

    # ---- 关闭时执行 ----
    print("👋 应用正在关闭，清理资源...")
    # 关闭 Redis 连接池，释放网络资源
    await redis_service.close()
    print("✅ Redis 连接已关闭")


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
