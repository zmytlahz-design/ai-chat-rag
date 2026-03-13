from __future__ import annotations
# ==================================================
# 对话管理服务（完整实现）
# 职责：协调 DB（持久化）、Redis（缓存）、RAGService（生成）三层
#
# ── 数据流向 ──────────────────────────────────────
#   写：  LLM 生成结果 → 精确缓存 + 语义缓存 + PostgreSQL
#   读：  精确缓存 → 语义缓存 → RAG（逐级降级）
#
# ── 三级缓存策略（RAG 答案层）──────────────────────
#   L1 精确缓存：MD5(问题) → 命中率约 30%，延迟 <1ms
#   L2 语义缓存：cosine sim ≥ 0.95 → 命中率约 20%，延迟 ~50ms（含 Embedding）
#   L3 RAG 全链路：向量检索 + LLM 生成 → 延迟 1-5s
#
#   预期总体命中率：~50%，整体平均响应时间可从 2s 降至 ~0.5s
#
# ── 多轮记忆（历史对话缓存）──────────────────────
#   等价于 ConversationBufferWindowMemory k=MAX_HISTORY_TURNS
#   只加载最近 10 轮（20 条），防止 token 超限
# ==================================================

import json
import logging
from datetime import datetime
from typing import Optional, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.conversation import Conversation
from models.message import Message
from services.redis_service import redis_service
from services.rag_service import rag_service

logger = logging.getLogger(__name__)

# 每个对话加载到上下文的最大历史轮数
# 1 轮 = 1条 user 消息 + 1条 assistant 消息
# 10 轮 = 最多 20 条消息
# 等价于 ConversationBufferWindowMemory(k=10)
MAX_HISTORY_TURNS = 10


class ChatService:
    """
    对话管理服务。

    对外提供两个核心接口：
      chat()        → 非流式，等待 LLM 完整回复后返回
      chat_stream() → 流式，逐 token 返回 SSE 事件字符串

    内部职责：
      1. 维护对话（Conversation）的创建与查找
      2. 加载、缓存、保存消息（Message）
      3. 调用 RAGService 执行实际的 RAG 链路
    """

    # --------------------------------------------------
    # 对话（Conversation）管理
    # --------------------------------------------------

    async def get_or_create_conversation(
        self,
        db: AsyncSession,
        kb_id: int,
        conversation_id: Optional[int] = None,
    ) -> Conversation:
        """
        获取已有对话，或创建新对话。

        逻辑：
          - 传入 conversation_id 且数据库存在 → 返回该对话
          - 传入 conversation_id 但不存在 → 抛出 ValueError
          - 未传入 conversation_id → 创建新对话，title 默认"新对话"

        注意：新对话的标题会在第一轮问答后通过 auto_generate_title 自动更新。
        """
        if conversation_id is not None:
            # 查询已有对话（同时验证 kb_id 匹配，防止跨知识库访问）
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.kb_id == kb_id,
                )
            )
            conv = result.scalar_one_or_none()

            if conv is None:
                raise ValueError(
                    f"对话 ID={conversation_id} 不存在，"
                    f"或不属于知识库 KB={kb_id}"
                )
            return conv

        # 创建新对话
        conv = Conversation(
            kb_id=kb_id,
            title="新对话",       # 临时标题，第一轮后会自动更新
            last_active_at=datetime.utcnow(),
        )
        db.add(conv)
        # flush：将 INSERT 发送到数据库并获取自增 ID，但暂不 commit（还在同一事务）
        await db.flush()
        await db.refresh(conv)   # 刷新对象，确保 created_at 等字段已从 DB 获取
        logger.info(f"新对话已创建：conv_id={conv.id}，kb_id={kb_id}")
        return conv

    async def update_conversation_title(
        self,
        db: AsyncSession,
        conversation_id: int,
        title: str,
    ) -> Conversation:
        """更新对话标题（用户手动重命名，或第一轮后自动命名）"""
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise ValueError(f"对话 ID={conversation_id} 不存在")

        conv.title = title[:100]  # 截取前 100 字符，防止标题过长
        await db.flush()
        return conv

    async def auto_generate_title(self, first_message: str) -> str:
        """
        根据第一条用户消息自动生成对话标题。
        取前 20 个字符 + 省略号，简单直观。
        后续可改为调用 LLM 生成更有意义的标题。
        """
        text = first_message.strip()
        if len(text) <= 20:
            return text
        return text[:20] + "..."

    # --------------------------------------------------
    # 历史记录管理（两级缓存：Redis → PostgreSQL）
    # --------------------------------------------------

    async def get_chat_history(
        self,
        db: AsyncSession,
        conversation_id: int,
    ) -> list[dict]:
        """
        获取对话历史（最近 MAX_HISTORY_TURNS 轮）。

        缓存策略（Cache-Aside 模式）：
          1. 先查 Redis（命中率通常 >90%，延迟 <1ms）
          2. 未命中 → 查 PostgreSQL → 写入 Redis（回填缓存）
          3. 返回消息列表（role + content 字典格式）

        窗口限制（等价于 ConversationBufferWindowMemory k=MAX_HISTORY_TURNS）：
          只返回最近 MAX_HISTORY_TURNS*2 条消息，
          防止历史过长超出 LLM 的 context window（token 限制）。
        """
        # ---- 第一级：查 Redis ----
        cached = await redis_service.get_chat_history(conversation_id)
        if cached:
            # 返回最近 N 轮（取后 N*2 条）
            window = MAX_HISTORY_TURNS * 2
            logger.debug(
                f"Redis 命中 conv_id={conversation_id}，"
                f"共 {len(cached)} 条，返回最近 {window} 条"
            )
            return cached[-window:]

        # ---- 第二级：查 PostgreSQL ----
        # ORDER BY created_at DESC LIMIT N → 取最新的 N 条（逆序）
        # 再 reversed() → 还原为正序（旧消息在前，符合对话时间线）
        window = MAX_HISTORY_TURNS * 2
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())   # 最新的在前
            .limit(window)
        )
        db_messages = list(reversed(result.scalars().all()))  # 翻转为时间正序

        history = [
            {"role": msg.role, "content": msg.content}
            for msg in db_messages
        ]

        # 回填 Redis 缓存（下次请求直接走缓存）
        if history:
            await redis_service.set_chat_history(conversation_id, history)
            logger.info(
                f"DB 加载历史 conv_id={conversation_id}，"
                f"{len(history)} 条已回填 Redis"
            )

        return history

    # --------------------------------------------------
    # 消息保存
    # --------------------------------------------------

    async def save_user_message(
        self,
        db: AsyncSession,
        conversation_id: int,
        content: str,
    ) -> Message:
        """
        保存用户消息到 PostgreSQL，并追加到 Redis 缓存。

        使用传入的 db session（与请求同一个事务），
        由调用方决定何时 commit。
        """
        msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=content,
        )
        db.add(msg)
        await db.flush()    # 获取自增 ID
        await db.refresh(msg)

        # 同步更新 Redis 缓存（追加，不全量覆盖）
        await redis_service.append_message(
            conversation_id,
            {"role": "user", "content": content},
        )

        logger.debug(f"用户消息已保存：msg_id={msg.id}，conv_id={conversation_id}")
        return msg

    async def save_assistant_message(
        self,
        db: AsyncSession,
        conversation_id: int,
        content: str,
        sources: Optional[list[dict]] = None,
        token_count: Optional[int] = None,
    ) -> Message:
        """
        保存 AI 助手消息到 PostgreSQL，并追加到 Redis 缓存。

        sources：引用的文档片段（JSON 列表，存入 messages.sources 字段）
        token_count：消耗的 token 数（可选，用于统计成本）
        """
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

        # 追加到 Redis
        await redis_service.append_message(
            conversation_id,
            {"role": "assistant", "content": content},
        )

        logger.debug(f"助手消息已保存：msg_id={msg.id}，conv_id={conversation_id}")
        return msg

    async def _update_conversation_active_time(
        self,
        db: AsyncSession,
        conv: Conversation,
    ) -> None:
        """更新对话的最后活跃时间（每次发送消息后调用）"""
        conv.last_active_at = datetime.utcnow()
        await db.flush()

    # --------------------------------------------------
    # 核心对话接口
    # --------------------------------------------------

    async def chat(
        self,
        db: AsyncSession,
        kb_id: int,
        user_message: str,
        conversation_id: Optional[int] = None,
    ) -> dict:
        """
        非流式对话，含三级缓存。

        完整流程（新增缓存层）：
          1. 获取/创建对话
          2. 加载历史
          3. 保存用户消息
          4. 记录热门问题统计
          5. 【L1】精确缓存查询 → 命中则跳过 6-7
          6. 【L2】语义缓存查询（需计算 Embedding）→ 命中则跳过 7
          7. 【L3】RAG 全链路（向量检索 + LLM 生成）
          8. 将结果写入精确缓存 + 语义缓存
          9. 保存 AI 回复到 DB
         10. 返回结果

        返回格式：
          {
            "conversation_id": 1,
            "message_id": 5,
            "content": "...",
            "sources": [...],
            "token_count": None,
            "from_cache": False    ← 新增：是否来自缓存，便于前端展示
          }
        """
        # ---- 1. 获取/创建对话 ----
        conv = await self.get_or_create_conversation(db, kb_id, conversation_id)
        is_new_conversation = (conversation_id is None)

        # ---- 2. 加载历史 ----
        history = await self.get_chat_history(db, conv.id)

        # ---- 3. 保存用户消息（立即持久化）----
        await self.save_user_message(db, conv.id, user_message)
        await db.commit()

        # ---- 4. 热门问题统计（无论是否命中缓存，都记录提问行为）----
        # ZINCRBY 是 O(log n)，极快，不会影响响应时间
        await redis_service.record_question(kb_id, user_message)

        # ---- 5. 【L1】精确缓存查询 ----
        # 条件：同一 kb_id + 归一化后完全相同的问题文本
        # 无需任何 API 调用，纯 Redis GET，延迟 <1ms
        exact_hit = await redis_service.get_exact_cache(kb_id, user_message)
        if exact_hit:
            logger.info(f"[L1 精确缓存命中] conv_id={conv.id}")
            return await self._finish_from_cache(
                db=db, conv=conv,
                answer=exact_hit["answer"],
                sources=exact_hit["sources"],
                is_new_conversation=is_new_conversation,
                user_message=user_message,
                from_cache=True,
            )

        # ---- 6. 【L2】语义缓存查询 ----
        # 先计算问题的 Embedding 向量，再与已缓存向量做余弦相似度比对
        # 此步骤需要调用 Embedding API（~100ms 网络延迟）
        # 如果命中：节省 ~1-4s 的 LLM 生成时间，整体仍比 RAG 快很多
        question_embedding: list[float] = []
        semantic_hit: Optional[dict] = None

        try:
            question_embedding = await rag_service.get_question_embedding(user_message)
            if question_embedding:
                semantic_hit = await redis_service.search_semantic_cache(
                    kb_id, question_embedding
                )
        except Exception as e:
            # Embedding 失败不阻断主流程，直接降级到 RAG
            logger.warning(f"语义缓存查询异常（降级到 RAG）：{e}")

        if semantic_hit:
            logger.info(f"[L2 语义缓存命中] conv_id={conv.id}")
            # 顺手把这个精确问题也写入精确缓存（下次精确匹配直接命中）
            await redis_service.set_exact_cache(
                kb_id, user_message,
                semantic_hit["answer"], semantic_hit["sources"]
            )
            return await self._finish_from_cache(
                db=db, conv=conv,
                answer=semantic_hit["answer"],
                sources=semantic_hit["sources"],
                is_new_conversation=is_new_conversation,
                user_message=user_message,
                from_cache=True,
            )

        # ---- 7. 【L3】RAG 全链路（缓存双未命中）----
        logger.info(f"[L3 RAG] 缓存未命中，走完整 RAG 链路：conv_id={conv.id}")
        try:
            answer_content, sources = await rag_service.generate_answer(
                question=user_message,
                kb_id=kb_id,
                chat_history=history,
            )
        except Exception as e:
            logger.error(f"RAG 生成失败：{e}", exc_info=True)
            raise

        # ---- 8. 写入缓存（异步后台，不阻塞返回）----
        # 精确缓存：下次完全相同的问题直接命中
        await redis_service.set_exact_cache(kb_id, user_message, answer_content, sources)
        # 语义缓存：下次语义相似的问题可命中（需要 question_embedding）
        if question_embedding:
            await redis_service.add_semantic_cache(
                kb_id, user_message, question_embedding, answer_content, sources
            )

        # ---- 9. 保存 AI 回复到 DB ----
        async with AsyncSessionLocal() as new_db:
            assistant_msg = await self.save_assistant_message(
                new_db, conv.id, answer_content, sources=sources
            )
            if is_new_conversation:
                title = await self.auto_generate_title(user_message)
                await self.update_conversation_title(new_db, conv.id, title)
                logger.info(f"对话标题已自动设置：'{title}'")
            result = await new_db.execute(
                select(Conversation).where(Conversation.id == conv.id)
            )
            conv_fresh = result.scalar_one_or_none()
            if conv_fresh:
                await self._update_conversation_active_time(new_db, conv_fresh)
            await new_db.commit()
            msg_id = assistant_msg.id

        logger.info(
            f"非流式 RAG 完成：conv_id={conv.id}，"
            f"回复 {len(answer_content)} 字，引用 {len(sources)} 片段"
        )
        return {
            "conversation_id": conv.id,
            "message_id": msg_id,
            "content": answer_content,
            "sources": sources,
            "token_count": None,
            "from_cache": False,
        }

    async def _finish_from_cache(
        self,
        db: AsyncSession,
        conv: "Conversation",
        answer: str,
        sources: list[dict],
        is_new_conversation: bool,
        user_message: str,
        from_cache: bool = True,
    ) -> dict:
        """
        缓存命中时的收尾处理（复用逻辑，减少代码重复）：
          1. 将缓存答案存入 DB（保证对话历史完整）
          2. 新对话自动命名
          3. 更新活跃时间
        """
        async with AsyncSessionLocal() as new_db:
            assistant_msg = await self.save_assistant_message(
                new_db, conv.id, answer, sources=sources
            )
            if is_new_conversation:
                title = await self.auto_generate_title(user_message)
                await self.update_conversation_title(new_db, conv.id, title)
            result = await new_db.execute(
                select(Conversation).where(Conversation.id == conv.id)
            )
            conv_fresh = result.scalar_one_or_none()
            if conv_fresh:
                await self._update_conversation_active_time(new_db, conv_fresh)
            await new_db.commit()
            msg_id = assistant_msg.id

        return {
            "conversation_id": conv.id,
            "message_id": msg_id,
            "content": answer,
            "sources": sources,
            "token_count": None,
            "from_cache": from_cache,
        }

    async def chat_stream(
        self,
        db: AsyncSession,
        kb_id: int,
        user_message: str,
        conversation_id: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        流式对话：逐 token 产出 SSE 格式字符串，供 StreamingResponse 消费。

        SSE（Server-Sent Events）格式规范：
          每个事件格式为 "data: {JSON}\n\n"（注意两个换行符）
          前端用 EventSource 或 fetch + ReadableStream 接收

        推送顺序：
          1. {"type": "start", "conversation_id": N}           对话开始
          2. {"type": "token", "content": "你"}                每个 token
          3. {"type": "token", "content": "好"}
          ...
          4. {"type": "done",  "message_id": N, "sources": [...]}  结束

        技术难点：
          流式结束后需要保存 AI 消息到 DB，但此时请求的 db session
          可能已处于不稳定状态，因此使用独立的 AsyncSessionLocal()。
        """
        # ---- 1. 获取/创建对话 ----
        conv = await self.get_or_create_conversation(db, kb_id, conversation_id)
        is_new_conversation = (conversation_id is None)

        # ---- 2. 加载历史 ----
        history = await self.get_chat_history(db, conv.id)

        # ---- 3. 保存用户消息，立即提交 ----
        await self.save_user_message(db, conv.id, user_message)
        await db.commit()

        # ---- 4. 热门问题统计 ----
        await redis_service.record_question(kb_id, user_message)

        # ==================================================
        # ---- 5. 【L1】精确缓存查询 ----
        # ==================================================
        # 精确缓存无需 API 调用，在 yield start 之前完成检查，
        # 命中时直接以"单 token"方式推送缓存内容，对前端透明。
        exact_hit = await redis_service.get_exact_cache(kb_id, user_message)
        if exact_hit:
            logger.info(f"[L1 精确缓存命中] 流式接口 conv_id={conv.id}")
            async for chunk in self._stream_from_cache(
                conv=conv,
                answer=exact_hit["answer"],
                sources=exact_hit["sources"],
                is_new_conversation=is_new_conversation,
                user_message=user_message,
                cache_level="L1_exact",
            ):
                yield chunk
            return

        # ==================================================
        # ---- 6. 【L2】语义缓存查询 ----
        # ==================================================
        question_embedding: list[float] = []
        semantic_hit: Optional[dict] = None

        try:
            question_embedding = await rag_service.get_question_embedding(user_message)
            if question_embedding:
                semantic_hit = await redis_service.search_semantic_cache(
                    kb_id, question_embedding
                )
        except Exception as e:
            logger.warning(f"语义缓存查询异常（降级到 RAG）：{e}")

        if semantic_hit:
            logger.info(f"[L2 语义缓存命中] 流式接口 conv_id={conv.id}")
            # 同时回写精确缓存
            await redis_service.set_exact_cache(
                kb_id, user_message,
                semantic_hit["answer"], semantic_hit["sources"]
            )
            async for chunk in self._stream_from_cache(
                conv=conv,
                answer=semantic_hit["answer"],
                sources=semantic_hit["sources"],
                is_new_conversation=is_new_conversation,
                user_message=user_message,
                cache_level="L2_semantic",
            ):
                yield chunk
            return

        # ==================================================
        # ---- 7. 【L3】RAG 全链路（流式）----
        # ==================================================
        logger.info(f"[L3 RAG] 流式 conv_id={conv.id}")
        yield _sse({"type": "start", "conversation_id": conv.id, "from_cache": False})

        full_response = ""
        sources: list[dict] = []

        try:
            async for event in rag_service.generate_answer_stream(
                question=user_message,
                kb_id=kb_id,
                chat_history=history,
            ):
                if event.get("type") == "token":
                    full_response += event["content"]
                    yield _sse({"type": "token", "content": event["content"]})
                elif event.get("type") == "sources":
                    sources = event.get("sources", [])

        except Exception as e:
            logger.error(f"流式 RAG 失败：{e}", exc_info=True)
            yield _sse({"type": "error", "message": f"生成回答时发生错误：{e}"})
            return

        # ---- 8. 写入缓存（RAG 完成后）----
        await redis_service.set_exact_cache(kb_id, user_message, full_response, sources)
        if question_embedding:
            await redis_service.add_semantic_cache(
                kb_id, user_message, question_embedding, full_response, sources
            )

        # ---- 9. 保存 AI 回复到 DB ----
        msg_id: Optional[int] = None
        try:
            async with AsyncSessionLocal() as new_db:
                assistant_msg = await self.save_assistant_message(
                    new_db, conv.id, content=full_response, sources=sources,
                )
                if is_new_conversation:
                    title = await self.auto_generate_title(user_message)
                    await self.update_conversation_title(new_db, conv.id, title)
                result = await new_db.execute(
                    select(Conversation).where(Conversation.id == conv.id)
                )
                conv_fresh = result.scalar_one_or_none()
                if conv_fresh:
                    await self._update_conversation_active_time(new_db, conv_fresh)
                await new_db.commit()
                msg_id = assistant_msg.id
        except Exception as e:
            logger.error(f"保存助手消息失败：{e}", exc_info=True)

        # ---- 10. 推送 done 事件 ----
        yield _sse({
            "type": "done",
            "conversation_id": conv.id,
            "message_id": msg_id,
            "sources": sources,
            "from_cache": False,
        })

        logger.info(
            f"流式 RAG 完成：conv_id={conv.id}，"
            f"回复 {len(full_response)} 字，引用 {len(sources)} 片段"
        )

    async def _stream_from_cache(
        self,
        conv: "Conversation",
        answer: str,
        sources: list[dict],
        is_new_conversation: bool,
        user_message: str,
        cache_level: str,
    ) -> AsyncIterator[str]:
        """
        缓存命中时的流式输出（供 L1/L2 共用）。

        为保持前端接口一致性，缓存命中时也走 SSE 格式，
        只是把完整答案作为一个 token 一次性推送（无打字机效果）。
        前端可通过 start 事件的 from_cache=True 字段决定是否展示"来自缓存"标识。

        推送顺序：
          data: {"type":"start", "from_cache":true, "cache_level":"L1_exact"}
          data: {"type":"token", "content":"完整答案文本"}
          data: {"type":"done",  "from_cache":true, ...}
        """
        yield _sse({
            "type": "start",
            "conversation_id": conv.id,
            "from_cache": True,
            "cache_level": cache_level,  # "L1_exact" or "L2_semantic"
        })

        # 将完整答案一次性推出（缓存命中无需逐 token 等待）
        yield _sse({"type": "token", "content": answer})

        # 保存到 DB（异步，保证对话历史完整）
        msg_id: Optional[int] = None
        try:
            async with AsyncSessionLocal() as new_db:
                assistant_msg = await self.save_assistant_message(
                    new_db, conv.id, content=answer, sources=sources,
                )
                if is_new_conversation:
                    title = await self.auto_generate_title(user_message)
                    await self.update_conversation_title(new_db, conv.id, title)
                result = await new_db.execute(
                    select(Conversation).where(Conversation.id == conv.id)
                )
                conv_fresh = result.scalar_one_or_none()
                if conv_fresh:
                    await self._update_conversation_active_time(new_db, conv_fresh)
                await new_db.commit()
                msg_id = assistant_msg.id
        except Exception as e:
            logger.error(f"缓存命中后保存消息失败：{e}", exc_info=True)

        yield _sse({
            "type": "done",
            "conversation_id": conv.id,
            "message_id": msg_id,
            "sources": sources,
            "from_cache": True,
            "cache_level": cache_level,
        })


# --------------------------------------------------
# 工具函数
# --------------------------------------------------

def _sse(data: dict) -> str:
    """
    将字典序列化为 SSE（Server-Sent Events）格式的字符串。

    SSE 格式规范（W3C）：
      每个事件以 "data: " 开头，以 "\n\n"（两个换行符）结尾。
      前端 EventSource 会在收到 "\n\n" 时触发 onmessage 事件。

    示例输出：
      'data: {"type": "token", "content": "你好"}\n\n'
    """
    # ensure_ascii=False：中文字符保持原样，不转义为 \uXXXX
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# 全局对话服务单例
chat_service = ChatService()
