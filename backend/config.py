# ==================================================
# 配置模块
# 使用 pydantic-settings 从环境变量（或 .env 文件）读取所有配置
# 好处：类型安全、自动验证、不需要手写 os.getenv()
# ==================================================

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    应用全局配置类。
    所有字段都可以通过同名环境变量覆盖（不区分大小写）。
    例如：DATABASE_URL=xxx python main.py
    也可以在 .env 文件中配置，会自动读取。
    """

    # ---------- 应用基本配置 ----------
    APP_NAME: str = Field(default="AI 知识库对话系统", description="应用名称")
    APP_VERSION: str = Field(default="0.1.0", description="应用版本")
    DEBUG: bool = Field(default=False, description="调试模式，生产环境务必设为 False")

    # ---------- 数据库配置（PostgreSQL）----------
    # asyncpg 驱动要求 URL 前缀为 postgresql+asyncpg://
    # 格式：postgresql+asyncpg://用户名:密码@主机:端口/数据库名
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/ai_chat_rag",
        description="PostgreSQL 异步连接字符串"
    )

    # ---------- Redis 配置 ----------
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接字符串，/0 表示使用第 0 号数据库"
    )
    REDIS_EXPIRE_SECONDS: int = Field(
        default=3600,
        description="Redis 缓存默认过期时间（秒），默认 1 小时"
    )

    # ---------- LLM 配置（DeepSeek，OpenAI 兼容格式）----------
    LLM_API_KEY: str = Field(
        default="your-deepseek-api-key",
        description="DeepSeek 或其他兼容 OpenAI 格式的 LLM API Key"
    )
    LLM_BASE_URL: str = Field(
        default="https://api.deepseek.com/v1",
        description="LLM API 基础地址，DeepSeek 兼容 OpenAI 格式"
    )
    LLM_MODEL_NAME: str = Field(
        default="deepseek-chat",
        description="使用的 LLM 模型名称"
    )
    LLM_TEMPERATURE: float = Field(
        default=0.7,
        description="LLM 生成温度，0-1 之间，越低越确定，越高越随机"
    )
    LLM_MAX_TOKENS: int = Field(
        default=2048,
        description="LLM 单次最大生成 token 数"
    )

    # ---------- Embedding 配置（智谱 AI 或 DeepSeek，OpenAI 兼容格式）----------
    EMBEDDING_API_KEY: str = Field(
        default="your-embedding-api-key",
        description="Embedding 模型的 API Key（可与 LLM 用同一个）"
    )
    EMBEDDING_BASE_URL: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="Embedding API 基础地址，默认使用智谱 AI"
    )
    EMBEDDING_MODEL_NAME: str = Field(
        default="embedding-3",
        description="Embedding 模型名称，智谱 AI 的向量模型"
    )
    EMBEDDING_DIMENSION: int = Field(
        default=2048,
        description="向量维度，需与 Embedding 模型输出维度一致，智谱 embedding-3 为 2048"
    )

    # ---------- 文档处理配置 ----------
    CHUNK_SIZE: int = Field(
        default=500,
        description="文档分块大小（字符数），每块最多 500 个字符"
    )
    CHUNK_OVERLAP: int = Field(
        default=50,
        description="相邻分块的重叠字符数，避免语义在分块边界断裂"
    )

    # ---------- CORS 配置 ----------
    # 允许跨域请求的前端地址列表，多个地址用逗号分隔
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="允许跨域的前端地址列表，5173 是 Vite 默认端口"
    )

    # ---------- pydantic-settings 元配置 ----------
    model_config = SettingsConfigDict(
        env_file=".env",          # 自动读取同目录下的 .env 文件
        env_file_encoding="utf-8",# .env 文件编码
        case_sensitive=False,     # 环境变量名不区分大小写
        extra="ignore",           # 忽略 .env 中多余的字段，不报错
    )


# 创建全局配置单例
# 整个项目通过 from config import settings 使用
settings = Settings()
