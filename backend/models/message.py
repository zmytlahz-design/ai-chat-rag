# ==================================================
# 消息数据库模型
# 对应数据库表：messages
# 一条消息属于一个对话，角色分为 user（用户）和 assistant（AI）
# ==================================================

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.conversation import Conversation


class Message(Base):
    """
    消息表。
    存储对话中每一轮的消息内容。
    role 字段遵循 OpenAI 消息格式：user / assistant / system
    """

    __tablename__ = "messages"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 外键：关联到对话
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属对话 ID"
    )

    # 消息角色：user（用户提问）/ assistant（AI 回答）/ system（系统提示词）
    # 遵循 OpenAI Chat API 的消息格式规范
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="消息角色：user / assistant / system"
    )

    # 消息正文内容，用 Text 类型支持长文本
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")

    # 引用来源：AI 回答时参考了哪些文档片段
    # 存储为 JSON 格式，例如：
    # [{"document_id": 1, "filename": "xx.pdf", "chunk_content": "...", "score": 0.92}]
    # 仅 assistant 消息有此字段，user 消息为 null
    sources: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="AI 回答时引用的文档片段（JSON 格式）"
    )

    # token 消耗：记录本条消息消耗的 token 数，用于统计费用
    token_count: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="本条消息消耗的 token 数"
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,  # 消息按时间排序查询较频繁，加索引
        comment="创建时间（UTC）"
    )

    # ---------- 关系定义 ----------

    # 多对一：多条消息属于同一个对话
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )

    def __repr__(self) -> str:
        # 截取前 50 个字符预览内容
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<Message id={self.id} role='{self.role}' content='{preview}'>"
