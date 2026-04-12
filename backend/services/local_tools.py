from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation
from models.document import Document
from models.knowledge_base import KnowledgeBase
from models.message import Message
from services.document_service import document_service


class LocalToolService:
    """本地工具集合：只查询当前系统的真实数据，不访问外网。"""

    async def _ensure_kb_exists(self, db: AsyncSession, kb_id: int) -> KnowledgeBase:
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise ValueError(f"知识库 ID={kb_id} 不存在")
        return kb

    async def get_kb_summary(self, db: AsyncSession, kb_id: int) -> dict[str, Any]:
        kb = await self._ensure_kb_exists(db, kb_id)

        rows = (
            await db.execute(
                select(Document.status, func.count(Document.id))
                .where(Document.kb_id == kb_id)
                .group_by(Document.status)
            )
        ).all()
        status_map = {status: int(count) for status, count in rows}

        latest_updated = (
            await db.execute(
                select(func.max(Document.updated_at)).where(Document.kb_id == kb_id)
            )
        ).scalar_one_or_none()

        document_total = int(sum(status_map.values()))
        return {
            "kb_id": kb_id,
            "kb_name": kb.name,
            "document_total": document_total,
            "document_completed": int(status_map.get("completed", 0)),
            "document_processing": int(
                status_map.get("processing", 0) + status_map.get("pending", 0)
            ),
            "document_failed": int(status_map.get("failed", 0)),
            "updated_at": latest_updated.isoformat() if latest_updated else None,
        }

    async def get_doc_status(
        self,
        db: AsyncSession,
        kb_id: int,
        limit: int = 50,
    ) -> dict[str, Any]:
        await self._ensure_kb_exists(db, kb_id)
        safe_limit = max(1, min(limit, 100))

        docs = (
            await db.execute(
                select(Document)
                .where(Document.kb_id == kb_id)
                .order_by(Document.created_at.desc())
                .limit(safe_limit)
            )
        ).scalars().all()

        return {
            "kb_id": kb_id,
            "items": [
                {
                    "doc_id": d.id,
                    "filename": d.filename,
                    "status": d.status,
                    "chunk_count": d.chunk_count,
                    "error_message": d.error_message,
                }
                for d in docs
            ],
        }

    async def get_conversation_stats(
        self,
        db: AsyncSession,
        kb_id: int,
        days: int = 7,
    ) -> dict[str, Any]:
        await self._ensure_kb_exists(db, kb_id)
        safe_days = max(1, min(days, 365))
        cutoff = datetime.utcnow() - timedelta(days=safe_days)

        conversation_count = (
            await db.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.kb_id == kb_id,
                    Conversation.last_active_at >= cutoff,
                )
            )
        ).scalar_one()

        message_count = (
            await db.execute(
                select(func.count(Message.id))
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(
                    Conversation.kb_id == kb_id,
                    Message.created_at >= cutoff,
                )
            )
        ).scalar_one()

        last_active_at = (
            await db.execute(
                select(func.max(Conversation.last_active_at)).where(
                    Conversation.kb_id == kb_id
                )
            )
        ).scalar_one_or_none()

        return {
            "kb_id": kb_id,
            "days": safe_days,
            "conversation_count": int(conversation_count or 0),
            "message_count": int(message_count or 0),
            "last_active_at": last_active_at.isoformat() if last_active_at else None,
        }

    async def kb_semantic_search(
        self,
        kb_id: int,
        query: str,
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> dict[str, Any]:
        safe_top_k = max(1, min(top_k, 10))
        hits = await document_service.search_similar_chunks(
            query=query,
            kb_id=kb_id,
            top_k=safe_top_k,
        )
        filtered = [hit for hit in hits if float(hit.get("score", 0.0)) >= min_score]
        return {
            "kb_id": kb_id,
            "query": query,
            "top_k": safe_top_k,
            "min_score": min_score,
            "hits": filtered,
        }

    @staticmethod
    def summarize_tool_result(tool_name: str, result: dict[str, Any]) -> str:
        if tool_name == "get_kb_summary":
            return (
                f"文档总数 {result.get('document_total', 0)}，"
                f"完成 {result.get('document_completed', 0)}，"
                f"处理中 {result.get('document_processing', 0)}，"
                f"失败 {result.get('document_failed', 0)}"
            )
        if tool_name == "get_doc_status":
            items = result.get("items", [])
            failed = sum(1 for it in items if it.get("status") == "failed")
            processing = sum(
                1 for it in items if it.get("status") in {"pending", "processing"}
            )
            return f"文档 {len(items)} 条，处理中 {processing}，失败 {failed}"
        if tool_name == "get_conversation_stats":
            return (
                f"近 {result.get('days')} 天，对话 {result.get('conversation_count', 0)}，"
                f"消息 {result.get('message_count', 0)}"
            )
        if tool_name == "kb_semantic_search":
            return f"命中 {len(result.get('hits', []))} 条高相关片段"
        if tool_name == "mcp_web_search":
            return f"联网检索命中 {len(result.get('hits', []))} 条结果"
        return "工具执行完成"


local_tool_service = LocalToolService()
