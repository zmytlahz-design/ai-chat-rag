from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.conversation import Conversation
from models.message import Message
from services.agent_service import agent_service
from services.rag_service import rag_service

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 10


class ChatService:
    async def get_or_create_conversation(
        self,
        db: AsyncSession,
        kb_id: int,
        conversation_id: Optional[int] = None,
    ) -> Conversation:
        if conversation_id is not None:
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.kb_id == kb_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                raise ValueError(
                    f"对话 ID={conversation_id} 不存在，或不属于知识库 KB={kb_id}"
                )
            return conv

        conv = Conversation(
            kb_id=kb_id,
            title="新对话",
            last_active_at=datetime.utcnow(),
        )
        db.add(conv)
        await db.flush()
        await db.refresh(conv)
        return conv

    async def update_conversation_title(
        self,
        db: AsyncSession,
        conversation_id: int,
        title: str,
    ) -> Conversation:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise ValueError(f"对话 ID={conversation_id} 不存在")
        conv.title = title[:100]
        await db.flush()
        return conv

    async def auto_generate_title(self, first_message: str) -> str:
        text = first_message.strip()
        return text if len(text) <= 20 else f"{text[:20]}..."

    async def get_chat_history(
        self,
        db: AsyncSession,
        conversation_id: int,
    ) -> list[dict]:
        window = MAX_HISTORY_TURNS * 2
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(window)
        )
        db_messages = list(reversed(result.scalars().all()))
        return [{"role": msg.role, "content": msg.content} for msg in db_messages]

    async def save_user_message(
        self,
        db: AsyncSession,
        conversation_id: int,
        content: str,
    ) -> Message:
        msg = Message(conversation_id=conversation_id, role="user", content=content)
        db.add(msg)
        await db.flush()
        await db.refresh(msg)
        return msg

    async def save_assistant_message(
        self,
        db: AsyncSession,
        conversation_id: int,
        content: str,
        sources: Optional[list[dict]] = None,
        token_count: Optional[int] = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            sources=sources,
            token_count=token_count,
        )
        db.add(msg)
        await db.flush()
        await db.refresh(msg)
        return msg

    async def _update_conversation_active_time(
        self,
        db: AsyncSession,
        conv: Conversation,
    ) -> None:
        conv.last_active_at = datetime.utcnow()
        await db.flush()

    async def chat(
        self,
        db: AsyncSession,
        kb_id: int,
        user_message: str,
        conversation_id: Optional[int] = None,
        mode: str = "rag",
    ) -> dict:
        conv = await self.get_or_create_conversation(db, kb_id, conversation_id)
        is_new_conversation = conversation_id is None

        history = await self.get_chat_history(db, conv.id)
        await self.save_user_message(db, conv.id, user_message)

        if mode == "rag_tools" and settings.ENABLE_TOOLS:
            answer_content, sources = await agent_service.generate_answer(
                db=db,
                question=user_message,
                kb_id=kb_id,
                chat_history=history,
            )
        else:
            answer_content, sources = await rag_service.generate_answer(
                question=user_message,
                kb_id=kb_id,
                chat_history=history,
            )
        assistant_msg = await self.save_assistant_message(
            db, conv.id, answer_content, sources=sources
        )

        if is_new_conversation:
            title = await self.auto_generate_title(user_message)
            await self.update_conversation_title(db, conv.id, title)

        await self._update_conversation_active_time(db, conv)
        await db.commit()

        return {
            "conversation_id": conv.id,
            "message_id": assistant_msg.id,
            "content": answer_content,
            "sources": sources,
            "token_count": None,
        }

    async def chat_stream(
        self,
        db: AsyncSession,
        kb_id: int,
        user_message: str,
        conversation_id: Optional[int] = None,
        mode: str = "rag",
    ) -> AsyncIterator[str]:
        conv = await self.get_or_create_conversation(db, kb_id, conversation_id)
        is_new_conversation = conversation_id is None
        history = await self.get_chat_history(db, conv.id)
        await self.save_user_message(db, conv.id, user_message)

        yield _sse({"type": "start", "conversation_id": conv.id})

        full_response = ""
        sources: list[dict] = []
        try:
            if mode == "rag_tools" and settings.ENABLE_TOOLS:
                stream_gen = agent_service.generate_answer_stream(
                    db=db,
                    question=user_message,
                    kb_id=kb_id,
                    chat_history=history,
                )
            else:
                stream_gen = rag_service.generate_answer_stream(
                    question=user_message,
                    kb_id=kb_id,
                    chat_history=history,
                )

            async for event in stream_gen:
                if event.get("type") == "token":
                    token = event.get("content", "")
                    full_response += token
                    yield _sse({"type": "token", "content": token})
                elif event.get("type") == "sources":
                    sources = event.get("sources", [])
                elif event.get("type") in {"tool_start", "tool_result"}:
                    yield _sse(event)
        except Exception as e:
            logger.error(f"流式 RAG 失败：{e}", exc_info=True)
            yield _sse({"type": "error", "message": f"生成回答时发生错误：{e}"})
            await db.rollback()
            return

        msg_id: Optional[int] = None
        try:
            assistant_msg = await self.save_assistant_message(
                db, conv.id, content=full_response, sources=sources
            )
            if is_new_conversation:
                title = await self.auto_generate_title(user_message)
                await self.update_conversation_title(db, conv.id, title)
            await self._update_conversation_active_time(db, conv)
            await db.commit()
            msg_id = assistant_msg.id
        except Exception as e:
            logger.error(f"保存流式消息失败：{e}", exc_info=True)
            await db.rollback()

        yield _sse(
            {
                "type": "done",
                "conversation_id": conv.id,
                "message_id": msg_id,
                "sources": sources,
            }
        )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


chat_service = ChatService()
