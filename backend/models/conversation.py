# ==================================================
# 对话数据库模型
# 对应数据库表：conversations
# 一个对话属于一个知识库，包含多条消息
# ==================================================

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.knowledge_base import KnowledgeBase
    from models.message import Message


class Conversation(Base):
    """
    对话表。
    代表用户与 AI 的一次完整对话会话。
    每个对话绑定一个知识库，AI 会基于该知识库的文档内容回答问题。
    """

    __tablename__ = "conversations"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 外键：关联到知识库
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属知识库 ID"
    )

    # 对话标题：可以由用户设置，也可以由第一条消息自动生成
    title: Mapped[str] = mapped_column(
        String(500),
        default="新对话",
        nullable=False,
        comment="对话标题"
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="创建时间（UTC）"
    )

    # 最后活跃时间：每次发送新消息时更新，用于排序展示最近对话
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="最后活跃时间（UTC）"
    )

    # ---------- 关系定义 ----------

    # 多对一：多个对话属于同一个知识库
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase",
        back_populates="conversations",
    )

    # 一对多：一个对话包含多条消息
    # cascade="all, delete-orphan"：删除对话时自动删除所有消息
    # order_by 按创建时间排序，保证消息顺序正确
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",  # 消息按时间升序排列
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} title='{self.title}' kb_id={self.kb_id}>"
