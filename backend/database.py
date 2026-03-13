# ==================================================
# 数据库模块
# 负责：创建异步数据库引擎、会话工厂、提供依赖注入函数
# 使用 SQLAlchemy 2.x async 模式 + asyncpg 驱动
# ==================================================

from sqlalchemy.ext.asyncio import (
    AsyncSession,           # 异步会话类型
    async_sessionmaker,     # 异步会话工厂（SQLAlchemy 2.x 推荐用法）
    create_async_engine,    # 创建异步引擎
)
from sqlalchemy.orm import DeclarativeBase  # ORM 模型基类

from config import settings  # 导入全局配置


# --------------------------------------------------
# 1. 创建异步数据库引擎
# --------------------------------------------------
# create_async_engine 对应同步的 create_engine
# echo=True 时会把所有 SQL 语句打印到控制台，调试很方便，生产环境应关闭
# pool_pre_ping=True：每次从连接池取连接前先 ping 一下，防止使用到断开的连接
# pool_size=10：连接池保持 10 个长连接
# max_overflow=20：连接池满时最多再多开 20 个临时连接
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,         # 调试模式下打印 SQL
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# --------------------------------------------------
# 2. 创建异步会话工厂
# --------------------------------------------------
# async_sessionmaker 是 SQLAlchemy 2.x 的异步版本 sessionmaker
# expire_on_commit=False：提交后对象属性不过期，避免再次访问时触发 lazy load（异步中会报错）
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# --------------------------------------------------
# 3. 声明 ORM 基类
# --------------------------------------------------
# 所有数据库模型类都要继承这个 Base
# SQLAlchemy 通过扫描 Base 的子类来知道有哪些表
class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类"""
    pass


# --------------------------------------------------
# 4. FastAPI 依赖注入函数
# --------------------------------------------------
async def get_db() -> AsyncSession:  # type: ignore[return]
    """
    FastAPI 路由依赖函数，用法：

        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...

    使用 async with 自动管理会话生命周期：
    - 请求进来时创建一个新会话
    - 请求结束时自动提交（如需手动控制请自行 commit）
    - 发生异常时自动回滚
    - 无论如何最终都会关闭会话，连接归还连接池
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session        # 将会话注入到路由函数中
            await session.commit()  # 路由正常结束后提交事务
        except Exception:
            await session.rollback()  # 出现异常时回滚，确保数据一致性
            raise                     # 继续向上抛出异常，让 FastAPI 处理


# --------------------------------------------------
# 5. 初始化数据库表
# --------------------------------------------------
async def init_db():
    """
    创建所有在 Base 中注册的表（如果表不存在的话）。
    在 main.py 的 lifespan 启动事件中调用一次即可。
    注意：这里用 checkfirst=True（即 CREATE TABLE IF NOT EXISTS）
    不会删除已有表，生产环境推荐用 Alembic 做迁移管理。
    """
    # 导入所有模型，确保它们已经注册到 Base.metadata
    # 必须在 create_all 之前导入，否则 SQLAlchemy 不知道要创建哪些表
    from models import knowledge_base, document, conversation, message  # noqa: F401

    async with engine.begin() as conn:
        # run_sync 让同步的 create_all 在异步环境中运行
        await conn.run_sync(Base.metadata.create_all)
