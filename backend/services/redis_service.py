# ==================================================
# Redis 缓存服务（完整实现）
#
# 本文件提供四大功能模块：
#
#  ① 对话历史缓存
#     Key：chat_history:{conversation_id}  →  JSON 消息列表
#     TTL：默认 1 小时，每次追加消息后刷新
#
#  ② RAG 精确匹配缓存（Exact Cache）
#     Key：rag_cache:exact:{kb_id}:{md5(question)}  →  JSON {answer, sources}
#     TTL：24 小时
#     策略：对问题文本做 MD5，同一知识库中完全相同的问题直接返回缓存
#     适用：高频重复问题（文档链接、产品定价等），响应 <1ms
#
#  ③ RAG 语义相似度缓存（Semantic Cache）
#     Key：rag_cache:semantic:{kb_id}  →  Redis Hash
#          field = UUID,  value = JSON {question, embedding, answer, sources, created_at}
#     TTL：按 created_at 过期（24小时），由 Python 层过滤（Hash 字段无独立 TTL）
#     策略：对问题做 Embedding，与已缓存问题计算余弦相似度
#           阈值 ≥ 0.95 时视为语义等价，直接返回缓存
#     适用：语义相近的不同表达，如"怎么退款"≈"退款流程是什么"
#
#  ④ 热门问题统计（Hot Questions）
#     Key：hot_questions:{kb_id}  →  Redis Sorted Set
#          member = 问题文本（截断 200 字符），score = 提问次数
#     操作：ZINCRBY 计数、ZREVRANGE 取 Top-N
#     适用：分析高频问题，优化知识库内容和缓存预热
#
# 面试要点：
#   当前同时实现精确匹配（O(1) 哈希查找）和语义缓存（O(n) 余弦相似度扫描）。
#   精确匹配覆盖完全相同的提问；语义缓存覆盖意思相同的不同表达。
#   未来可将语义缓存升级为 Redis Stack 的向量索引（HNSW），降为 O(log n)。
# ==================================================

import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

# ---- 常量配置 ----
RAG_CACHE_TTL_SECONDS = 86_400          # 24 小时（精确缓存 TTL）
SEMANTIC_CACHE_TTL_HOURS = 24           # 语义缓存有效期
SEMANTIC_CACHE_MAX_ENTRIES = 500        # 每个知识库最多缓存 500 条（防止 Redis 内存暴涨）
SEMANTIC_SIMILARITY_THRESHOLD = 0.95   # 余弦相似度阈值，≥ 此值视为语义等价


# ==================================================
# 工具函数（模块级，不依赖 Redis 连接）
# ==================================================

def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    计算两个向量的余弦相似度。
    公式：cos(θ) = (A·B) / (|A| × |B|)

    余弦相似度范围 [-1, 1]，越接近 1 越相似：
      1.0  → 完全相同的语义
      0.95 → 非常接近（我们的阈值）
      0.7  → 主题相关但表达不同
      0.0  → 完全无关

    使用 Python 内置的 math 和 sum，避免引入 numpy 额外依赖。
    对于 2048 维向量，单次计算约需 <0.1ms，500 条缓存的全量扫描 <50ms。
    """
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    # 点积：∑(a_i × b_i)
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    # 模长：sqrt(∑(a_i²))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def _md5(text: str) -> str:
    """
    计算字符串的 MD5 哈希，用作精确缓存的 key 后缀。
    先 strip().lower() 做归一化，提高精确命中率。
    例如："  什么是 RAG？ " 和 "什么是 rag？" 会映射到同一个 key。
    """
    normalized = text.strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


class RedisService:
    """
    Redis 缓存服务（统一入口）。
    延迟初始化（Lazy Init）：应用启动时不建立连接，首次调用时才创建。
    所有方法均有 try/except 保护：Redis 故障不会影响主业务，只记录警告日志。
    """

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    async def get_client(self) -> aioredis.Redis:
        """
        获取 Redis 客户端（单例 + 连接池）。
        decode_responses=True：所有命令的返回值自动从 bytes 解码为 str。
        """
        if self._client is None:
            self._client = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info(f"Redis 连接已初始化：{settings.REDIS_URL}")
        return self._client

    async def close(self) -> None:
        """关闭连接池（在应用 shutdown 的 lifespan 中调用）"""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis 连接已关闭")

    # ==================================================
    # ① 对话历史缓存
    # ==================================================

    def _history_key(self, conversation_id: int) -> str:
        return f"chat_history:{conversation_id}"

    async def get_chat_history(self, conversation_id: int) -> list[dict]:
        """
        读取对话历史（未命中返回空列表，调用方降级查数据库）。
        """
        try:
            client = await self.get_client()
            raw = await client.get(self._history_key(conversation_id))
            if raw is None:
                return []
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Redis get_chat_history 失败：{e}")
            return []

    async def set_chat_history(
        self,
        conversation_id: int,
        messages: list[dict],
        expire_seconds: Optional[int] = None,
    ) -> None:
        """全量写入对话历史（首次从 DB 加载后回填用）"""
        try:
            client = await self.get_client()
            ttl = expire_seconds or settings.REDIS_EXPIRE_SECONDS
            await client.setex(
                self._history_key(conversation_id),
                ttl,
                json.dumps(messages, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning(f"Redis set_chat_history 失败：{e}")

    async def append_message(self, conversation_id: int, message: dict) -> None:
        """
        向对话历史追加一条消息，并刷新 TTL。
        GET → 追加 → SETEX（原子性不强但对缓存场景可接受）。
        """
        try:
            client = await self.get_client()
            key = self._history_key(conversation_id)
            raw = await client.get(key)
            msgs: list[dict] = json.loads(raw) if raw else []
            msgs.append(message)
            await client.setex(
                key,
                settings.REDIS_EXPIRE_SECONDS,
                json.dumps(msgs, ensure_ascii=False),
            )
        except Exception as e:
            logger.warning(f"Redis append_message 失败：{e}")

    async def delete_chat_history(self, conversation_id: int) -> None:
        """删除对话历史缓存（对话被删除时调用）"""
        try:
            client = await self.get_client()
            await client.delete(self._history_key(conversation_id))
        except Exception as e:
            logger.warning(f"Redis delete_chat_history 失败：{e}")

    # ==================================================
    # ② RAG 精确匹配缓存（Exact Cache）
    # ==================================================
    #
    # 设计思路：
    #   把 (kb_id + 问题MD5) 拼成 Redis key，对应值存 JSON 格式的答案。
    #   命中条件：同一知识库 + 归一化后完全相同的问题文本。
    #   TTL 24 小时：知识库文档可能更新，避免缓存过旧答案。
    # ==================================================

    def _exact_cache_key(self, kb_id: int, question: str) -> str:
        """
        构造精确缓存 key。
        格式：rag_cache:exact:{kb_id}:{md5(归一化问题)}
        示例：rag_cache:exact:1:a3f2b1c9d8e7...
        """
        return f"rag_cache:exact:{kb_id}:{_md5(question)}"

    async def get_exact_cache(
        self,
        kb_id: int,
        question: str,
    ) -> Optional[dict]:
        """
        查询精确匹配缓存。

        返回：{"answer": "...", "sources": [...]}  命中时
              None                                  未命中时

        特点：纯 Redis GET，无网络 API 调用，延迟 <1ms。
        """
        try:
            client = await self.get_client()
            key = self._exact_cache_key(kb_id, question)
            raw = await client.get(key)
            if raw is None:
                return None

            result = json.loads(raw)
            logger.info(f"精确缓存命中：kb_id={kb_id}，问题='{question[:30]}'")
            return result

        except Exception as e:
            logger.warning(f"精确缓存查询失败（将继续走 RAG）：{e}")
            return None

    async def set_exact_cache(
        self,
        kb_id: int,
        question: str,
        answer: str,
        sources: list[dict],
    ) -> None:
        """
        将 RAG 答案写入精确缓存，TTL 24 小时。

        写入时机：RAG 成功生成答案之后调用，缓存供下次相同问题直接命中。
        """
        try:
            client = await self.get_client()
            key = self._exact_cache_key(kb_id, question)
            value = json.dumps(
                {"answer": answer, "sources": sources},
                ensure_ascii=False,
            )
            # SETEX key seconds value：原子操作，设置值 + 过期时间
            await client.setex(key, RAG_CACHE_TTL_SECONDS, value)
            logger.debug(
                f"精确缓存已写入：kb_id={kb_id}，问题='{question[:30]}'，"
                f"TTL={RAG_CACHE_TTL_SECONDS}s"
            )
        except Exception as e:
            logger.warning(f"精确缓存写入失败（不影响答案返回）：{e}")

    async def delete_kb_cache(self, kb_id: int) -> None:
        """
        删除某知识库的所有 RAG 缓存（知识库文档更新时调用）。
        使用 SCAN 命令（非阻塞）逐批扫描，安全删除所有匹配的 key。
        注意：KEYS 命令是阻塞的，生产环境禁止使用，必须用 SCAN。
        """
        try:
            client = await self.get_client()
            # 删除精确缓存：pattern = rag_cache:exact:{kb_id}:*
            pattern = f"rag_cache:exact:{kb_id}:*"
            deleted_count = 0
            async for key in client.scan_iter(match=pattern, count=100):
                await client.delete(key)
                deleted_count += 1
            # 删除语义缓存 Hash
            await client.delete(self._semantic_store_key(kb_id))
            logger.info(
                f"知识库 kb_id={kb_id} 的缓存已清空：精确缓存 {deleted_count} 条，"
                f"语义缓存 1 个 Hash"
            )
        except Exception as e:
            logger.warning(f"删除知识库缓存失败：{e}")

    # ==================================================
    # ③ 语义相似度缓存（Semantic Cache）
    # ==================================================
    #
    # 设计思路：
    #   将每条缓存的问题向量存入 Redis Hash，查询时全量读出并计算余弦相似度。
    #   命中条件：余弦相似度 ≥ SEMANTIC_SIMILARITY_THRESHOLD（默认 0.95）。
    #
    # 存储结构：
    #   Key：rag_cache:semantic:{kb_id}
    #   Type：Redis Hash
    #     field：UUID（唯一标识每条缓存）
    #     value：JSON 字符串 {
    #       "question": "原始问题",
    #       "embedding": [0.1, 0.2, ...],   # 2048 维浮点数组
    #       "answer": "LLM 的回答",
    #       "sources": [...],                # 引用文档
    #       "created_at": "ISO 格式时间戳"
    #     }
    #
    # 过期策略：
    #   Hash 字段没有独立 TTL，在 Python 层检查 created_at 过滤过期条目，
    #   并在写入新条目时顺手清理旧条目（Lazy Expiration）。
    #
    # 容量限制：
    #   每个知识库最多 SEMANTIC_CACHE_MAX_ENTRIES（500）条，
    #   超出时删除最旧的条目（LRU 近似）。
    #
    # 面试升级路径：
    #   当前：O(n) 全量扫描 + Python 计算相似度（适合 <1000 条缓存）
    #   升级：Redis Stack + HNSW 向量索引 → O(log n) ANN 搜索，
    #         使用 redis.commands.search.Query 进行向量查询。
    # ==================================================

    def _semantic_store_key(self, kb_id: int) -> str:
        """语义缓存 Hash 的 key：rag_cache:semantic:{kb_id}"""
        return f"rag_cache:semantic:{kb_id}"

    async def search_semantic_cache(
        self,
        kb_id: int,
        question_embedding: list[float],
        threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
    ) -> Optional[dict]:
        """
        在语义缓存中搜索相似问题。

        算法步骤：
          1. HGETALL 取出该知识库的所有缓存条目（一次 Redis 读）
          2. 逐条检查 created_at，过滤 24 小时前的过期条目
          3. 计算问题向量与每条缓存向量的余弦相似度
          4. 找出相似度最高且 ≥ threshold 的条目返回

        性能分析：
          500 条 × 2048 维 = 约 100 万次乘法，Python 执行 <10ms（可接受）。
          缓存条目较少时（< 100 条）通常 <1ms。

        返回：{"answer": "...", "sources": [...]}  命中时
              None                                  未命中时
        """
        try:
            client = await self.get_client()
            key = self._semantic_store_key(kb_id)

            # HGETALL：返回 {field: value} 字典，全部是字符串（decode_responses=True）
            raw_entries: dict[str, str] = await client.hgetall(key)

            if not raw_entries:
                return None  # 缓存为空

            now = datetime.utcnow()
            expire_before = now - timedelta(hours=SEMANTIC_CACHE_TTL_HOURS)

            best_score = 0.0
            best_answer: Optional[str] = None
            best_sources: list = []

            for _field, raw_value in raw_entries.items():
                try:
                    entry = json.loads(raw_value)
                except json.JSONDecodeError:
                    continue  # 跳过损坏的条目

                # 过滤过期条目（Lazy Expiration）
                created_at = datetime.fromisoformat(entry.get("created_at", "2000-01-01"))
                if created_at < expire_before:
                    continue

                # 计算余弦相似度
                cached_embedding: list[float] = entry.get("embedding", [])
                if not cached_embedding:
                    continue

                similarity = _cosine_similarity(question_embedding, cached_embedding)

                if similarity > best_score:
                    best_score = similarity
                    best_answer = entry.get("answer", "")
                    best_sources = entry.get("sources", [])

            if best_score >= threshold:
                logger.info(
                    f"语义缓存命中：kb_id={kb_id}，"
                    f"相似度={best_score:.4f}（阈值={threshold}）"
                )
                return {"answer": best_answer, "sources": best_sources}

            logger.debug(
                f"语义缓存未命中：kb_id={kb_id}，"
                f"最高相似度={best_score:.4f} < {threshold}"
            )
            return None

        except Exception as e:
            logger.warning(f"语义缓存查询失败（将继续走 RAG）：{e}")
            return None

    async def add_semantic_cache(
        self,
        kb_id: int,
        question: str,
        question_embedding: list[float],
        answer: str,
        sources: list[dict],
    ) -> None:
        """
        将新的 QA 对写入语义缓存。

        写入步骤：
          1. 清理已过期的条目（Lazy Expiration）
          2. 若超过最大条目数（500），删除最旧的若干条
          3. HSET 写入新条目

        写入时机：RAG 成功生成答案，且缓存未命中时调用。
        """
        try:
            client = await self.get_client()
            key = self._semantic_store_key(kb_id)

            # ---- 清理过期 + 超量条目 ----
            raw_entries: dict[str, str] = await client.hgetall(key)
            now = datetime.utcnow()
            expire_before = now - timedelta(hours=SEMANTIC_CACHE_TTL_HOURS)

            # 解析所有条目，保留未过期的
            valid_entries: list[tuple[str, dict]] = []
            expired_fields: list[str] = []

            for field, raw_value in raw_entries.items():
                try:
                    entry = json.loads(raw_value)
                    created_at = datetime.fromisoformat(
                        entry.get("created_at", "2000-01-01")
                    )
                    if created_at < expire_before:
                        expired_fields.append(field)
                    else:
                        valid_entries.append((field, entry))
                except (json.JSONDecodeError, ValueError):
                    expired_fields.append(field)  # 损坏的条目也删掉

            # 批量删除过期条目
            if expired_fields:
                await client.hdel(key, *expired_fields)
                logger.debug(f"语义缓存：清理 {len(expired_fields)} 条过期条目")

            # 超量时按 created_at 升序排序，删除最旧的
            if len(valid_entries) >= SEMANTIC_CACHE_MAX_ENTRIES:
                # 按 created_at 升序（最旧的在前）
                valid_entries.sort(
                    key=lambda x: x[1].get("created_at", "2000-01-01")
                )
                # 计算需要删除的数量（删到 499 条，为新条目留空间）
                to_delete = valid_entries[: len(valid_entries) - SEMANTIC_CACHE_MAX_ENTRIES + 1]
                delete_fields = [f for f, _ in to_delete]
                await client.hdel(key, *delete_fields)
                logger.debug(
                    f"语义缓存：超量删除 {len(delete_fields)} 条最旧条目"
                )

            # ---- 写入新条目 ----
            entry_id = str(uuid.uuid4())  # 生成唯一 field 名
            entry_data = {
                "question": question,
                "embedding": question_embedding,   # list[float]，JSON 序列化为数组
                "answer": answer,
                "sources": sources,
                "created_at": now.isoformat(),     # ISO 格式时间戳，便于解析
            }
            # HSET key field value：设置 Hash 中的一个字段
            await client.hset(key, entry_id, json.dumps(entry_data, ensure_ascii=False))

            logger.debug(
                f"语义缓存写入：kb_id={kb_id}，问题='{question[:30]}'，"
                f"entry_id={entry_id[:8]}..."
            )

        except Exception as e:
            logger.warning(f"语义缓存写入失败（不影响答案返回）：{e}")

    # ==================================================
    # ④ 热门问题统计（Hot Questions）
    # ==================================================
    #
    # 使用 Redis Sorted Set 实现计数器：
    #   - member：问题文本（截断 200 字符）
    #   - score：被提问次数（每次 +1）
    #
    # Sorted Set 特性：
    #   - ZINCRBY：O(log n) 时间复杂度，原子性自增
    #   - ZREVRANGE：O(log n + k) 取 Top-k，结果按 score 降序排列
    #   - 成员唯一：同一个问题只有一个 member，score 累加
    # ==================================================

    def _hot_questions_key(self, kb_id: int) -> str:
        """热门问题 Sorted Set 的 key：hot_questions:{kb_id}"""
        return f"hot_questions:{kb_id}"

    async def record_question(self, kb_id: int, question: str) -> None:
        """
        记录一次提问，在热门问题统计中计数。

        ZINCRBY key increment member：
          - 如果 member 不存在，以 increment 为初始 score 创建
          - 如果 member 已存在，score += increment
          - 时间复杂度：O(log n)

        问题文本截断：Sorted Set 的 member 存原始文本（最多 200 字符），
        太长的问题截断处理，保证展示时可读。
        """
        try:
            client = await self.get_client()
            key = self._hot_questions_key(kb_id)
            # 截断问题文本，防止 member 过长占用内存
            member = question.strip()[:200]
            # ZINCRBY：原子性地将 member 的 score 增加 1
            await client.zincrby(key, 1, member)
        except Exception as e:
            logger.warning(f"热门问题统计写入失败：{e}")

    async def get_hot_questions(
        self,
        kb_id: int,
        top_n: int = 10,
    ) -> list[dict]:
        """
        获取某知识库的热门问题 Top-N，按提问次数降序排列。

        ZREVRANGE key start stop WITHSCORES：
          - rev：降序（高分在前）
          - start=0, stop=top_n-1：取前 top_n 条
          - withscores=True：同时返回 score（提问次数）
          - 返回格式：[(member1, score1), (member2, score2), ...]

        返回格式：[
          {"question": "什么是 RAG？", "count": 42},
          {"question": "如何上传文档？", "count": 35},
          ...
        ]
        """
        try:
            client = await self.get_client()
            key = self._hot_questions_key(kb_id)
            # zrevrange with withscores=True 返回 [(str, float), ...]
            results = await client.zrevrange(key, 0, top_n - 1, withscores=True)
            return [
                {"question": member, "count": int(score)}
                for member, score in results
            ]
        except Exception as e:
            logger.warning(f"获取热门问题失败：{e}")
            return []

    async def reset_hot_questions(self, kb_id: int) -> None:
        """
        清空某知识库的热门问题统计（知识库删除时或手动重置时调用）。
        """
        try:
            client = await self.get_client()
            await client.delete(self._hot_questions_key(kb_id))
            logger.info(f"热门问题统计已重置：kb_id={kb_id}")
        except Exception as e:
            logger.warning(f"重置热门问题失败：{e}")

    # ==================================================
    # 通用基础操作（供其他模块复用）
    # ==================================================

    async def get(self, key: str) -> Optional[str]:
        """通用 GET"""
        try:
            return await (await self.get_client()).get(key)
        except Exception as e:
            logger.warning(f"Redis GET {key} 失败：{e}")
            return None

    async def set(
        self,
        key: str,
        value: str,
        expire_seconds: Optional[int] = None,
    ) -> None:
        """通用 SET，可选 TTL"""
        try:
            client = await self.get_client()
            if expire_seconds:
                await client.setex(key, expire_seconds, value)
            else:
                await client.set(key, value)
        except Exception as e:
            logger.warning(f"Redis SET {key} 失败：{e}")

    async def delete(self, key: str) -> None:
        """通用 DEL"""
        try:
            await (await self.get_client()).delete(key)
        except Exception as e:
            logger.warning(f"Redis DEL {key} 失败：{e}")

    async def exists(self, key: str) -> bool:
        """检查 key 是否存在"""
        try:
            return bool(await (await self.get_client()).exists(key))
        except Exception as e:
            logger.warning(f"Redis EXISTS {key} 失败：{e}")
            return False


# 全局单例
redis_service = RedisService()
