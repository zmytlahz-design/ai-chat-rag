# ==================================================
# 文档数据库模型
# 对应数据库表：documents
# 一个文档属于一个知识库，上传后会被分块并向量化存储
# ==================================================

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.knowledge_base import KnowledgeBase


class Document(Base):
    """
    文档表。
    记录上传到知识库的每个文档的元数据。
    文档的实际向量内容存储在 pgvector 中（由 LangChain 管理），
    这张表只存文档的基本信息，方便管理和展示。
    """

    __tablename__ = "documents"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 外键：关联到 knowledge_bases 表的 id
    # ondelete="CASCADE"：数据库层面的级联删除（知识库删了，文档也删）
    # 配合 SQLAlchemy 的 cascade="all, delete-orphan" 双重保险
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # 加索引，按知识库查询文档时更快
        comment="所属知识库 ID"
    )

    # 原始文件名（用户上传时的文件名）
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")

    # 文件类型：pdf / docx / txt 等
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="文件类型扩展名")

    # 文件大小（字节）
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="文件大小（字节）")

    # 分块数量：文档被切分成多少个 chunk，向量化后存入 pgvector
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="文档被切分的块数"
    )

    # 处理状态：pending（待处理）/ processing（处理中）/ completed（完成）/ failed（失败）
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
        comment="文档处理状态：pending/processing/completed/failed"
    )

    # 失败原因（当 status=failed 时记录错误信息）
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处理失败时的错误信息")

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="创建时间（UTC）"
    )

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="最后更新时间（UTC）"
    )

    # ---------- 关系定义 ----------

    # 多对一：多个文档属于同一个知识库
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase",
        back_populates="documents",
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename='{self.filename}' kb_id={self.kb_id}>"
