# ==================================================
# 知识库数据库模型
# 对应数据库表：knowledge_bases
# 一个知识库可以包含多个文档和多个对话
# ==================================================

from datetime import datetime                   # 时间类型
from typing import TYPE_CHECKING               # 避免循环导入时使用

from sqlalchemy import String, Text, DateTime  # 列类型
from sqlalchemy.orm import Mapped, mapped_column, relationship
# Mapped      : 标注列的 Python 类型（SQLAlchemy 2.x 风格）
# mapped_column: 定义列的数据库属性（SQLAlchemy 2.x 风格）
# relationship : 定义表间关系（一对多等）

from database import Base  # 导入公共基类

# TYPE_CHECKING 块中的导入只在类型检查时生效，运行时不导入
# 用于解决模型之间的循环引用问题（Document 引用 KnowledgeBase，KnowledgeBase 也引用 Document）
if TYPE_CHECKING:
    from models.document import Document
    from models.conversation import Conversation


class KnowledgeBase(Base):
    """
    知识库表。
    一个知识库是一组相关文档的集合，是 RAG 系统的基本组织单元。
    """

    # SQLAlchemy 通过 __tablename__ 知道这个类对应哪张表
    __tablename__ = "knowledge_bases"

    # ---------- 列定义 ----------

    # 主键：自增整数 ID
    # Mapped[int] 告诉类型检查器这个字段是 int 类型
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 知识库名称：最长 255 字符，不允许为空，加索引方便搜索
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="知识库名称")

    # 知识库描述：可为空，用 Text 类型存储较长文本
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库描述")

    # 创建时间：插入时自动设置为当前 UTC 时间
    # default=datetime.utcnow 是 Python 层面的默认值（在 INSERT 时由 SQLAlchemy 设置）
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="创建时间（UTC）"
    )

    # 更新时间：每次更新时自动刷新
    # onupdate=datetime.utcnow 表示每次 UPDATE 时自动更新这个字段
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="最后更新时间（UTC）"
    )

    # ---------- 关系定义 ----------

    # 一个知识库拥有多个文档（一对多关系）
    # back_populates="knowledge_base" 对应 Document 模型中的同名属性，双向关联
    # cascade="all, delete-orphan"：删除知识库时，自动级联删除其下所有文档
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="select",  # 默认懒加载，异步环境中需要显式 joinedload
    )

    # 一个知识库拥有多个对话（一对多关系）
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        """调试时打印对象的友好字符串表示"""
        return f"<KnowledgeBase id={self.id} name='{self.name}'>"
