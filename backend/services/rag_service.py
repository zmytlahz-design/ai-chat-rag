# ==================================================
# RAG 服务（完整实现）
# Retrieval-Augmented Generation：检索增强生成
#
# 整体链路（对应 LangChain ConversationalRetrievalChain 概念）：
#
#   用户问题 + 历史对话
#       │
#       ▼
#   ① 问题浓缩（Condense Question）
#       将 "那它是什么颜色的？" + 历史改写为 "苹果是什么颜色的？"
#       使用 self.condense_llm（非流式，速度快）
#       │
#       ▼
#   ② 向量检索（Retrieval）
#       将浓缩后的问题 Embedding，在 pgvector 中做 ANN 搜索
#       返回最相关的 top-k 个文档片段
#       │
#       ▼
#   ③ 答案生成（Generation）
#       将 {context（检索结果）+ chat_history + 问题} 注入 Prompt
#       使用 self.llm（流式，实时推送 token）
#
# 为什么自己实现而不用 ConversationalRetrievalChain？
#   ConversationalRetrievalChain 不支持将 chat_history 传入最终 QA 步骤，
#   而用户要求同时在 Prompt 里展示 {context} 和 {chat_history}。
#   本实现手动拆解三步，等价于 ConversationalRetrievalChain 的内部逻辑，
#   但拥有完整控制权，支持 async 流式输出。
# ==================================================

import asyncio
import logging
from typing import AsyncIterator

from langchain_core.output_parsers import StrOutputParser
# StrOutputParser：将 LLM 返回的 AIMessage 对象解析为纯字符串
# 用在 condense 链末尾：AIMessage("苹果是什么颜色？") → "苹果是什么颜色？"

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
# ChatPromptTemplate：多角色提示词模板（system / human / ai）
# PromptTemplate：单段文本模板（用于问题浓缩，不需要角色区分）

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
# LangChain 的消息类型：
#   HumanMessage  → role: "user"
#   AIMessage     → role: "assistant"
#   BaseMessage   → 以上的公共基类

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
# ChatOpenAI：封装了 OpenAI Chat Completion API
#   通过 openai_api_base 可指向智谱 BigModel 等 OpenAI 兼容服务
# OpenAIEmbeddings：封装了 OpenAI Embedding API
#   通过 openai_api_base 替换为智谱 AI 等兼容服务

from langchain_postgres import PGVector
# PGVector：LangChain 官方的 pgvector 向量库集成
#   内部使用 psycopg3 同步连接，所以必须在 asyncio.to_thread 中调用

from config import settings
from services.document_service import SUPPORTED_EXTENSIONS  # 只为类型标注导入

logger = logging.getLogger(__name__)


# ==================================================
# Prompt 模板定义
# ==================================================

# ---- ① 问题浓缩 Prompt ----
# 将"依赖上下文的问题"改写为"独立问题"，以便向量检索时不受代词影响
# 对应 ConversationalRetrievalChain 的 condense_question_prompt
CONDENSE_QUESTION_PROMPT = PromptTemplate.from_template(
    """你是一个问题改写助手。根据以下对话历史和用户的最新问题，\
将最新问题改写为一个独立完整的问题（不依赖上下文也能理解）。
如果最新问题本身已经独立，请原样返回，不要修改任何内容。
只返回改写后的问题，不要解释，不要加引号。

对话历史：
{chat_history}

最新问题：{question}

独立问题："""
)

# ---- ② 最终答案生成 Prompt ----
# 同时提供 {context}（检索到的文档）和 {chat_history}（历史对话）
# 对应 ConversationalRetrievalChain 的 combine_docs_chain_kwargs["prompt"]
QA_SYSTEM_TEMPLATE = """\
你是一个专业的知识库助手。根据以下检索到的文档内容回答用户问题。

规则：
1. 只基于提供的文档内容回答，不要编造信息
2. 如果文档中没有相关信息，明确告知用户
3. 回答要结构清晰，适当使用 Markdown 格式
4. 在回答末尾标注引用来源 [来源：文件名]

检索到的文档内容：
{context}

历史对话：
{chat_history}\
"""

QA_PROMPT = ChatPromptTemplate.from_messages([
    # system 消息：给 AI 角色定位和文档上下文
    ("system", QA_SYSTEM_TEMPLATE),
    # human 消息：用户当前问题（用浓缩后的问题，语义更清晰）
    ("human", "{question}"),
])


class RAGService:
    """
    RAG 核心服务。
    封装了"问题浓缩 → 向量检索 → 答案生成"三步链路。

    LangChain 组件对照：
      self.llm           ↔  chain 中的 answer LLM
      self.condense_llm  ↔  chain 中的 question_generator LLM
      self.embeddings    ↔  retriever 内部的 embedding 模型
      _get_retriever_sync ↔  chain.retriever
      CONDENSE_QUESTION_PROMPT ↔  chain.condense_question_prompt
      QA_PROMPT          ↔  chain.combine_docs_chain_kwargs["prompt"]
    """

    def __init__(self):
        # ---- LLM：用于最终答案生成（支持流式）----
        # streaming=True：开启流式模式，llm.astream() 才会逐 token 返回
        # temperature：控制随机性，0.7 在创意和准确性间取得平衡
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_NAME,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            streaming=True,   # 必须为 True，astream() 才能逐 token 推送
        )

        # ---- Condense LLM：用于问题浓缩（不需要流式，速度优先）----
        # 浓缩步骤只需要一个简短的改写结果，无需流式输出
        # 使用 temperature=0 让改写结果更确定、不发散
        self.condense_llm = ChatOpenAI(
            model=settings.LLM_MODEL_NAME,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=0,      # 问题改写追求确定性，温度设为 0
            max_tokens=256,     # 浓缩后的问题不会很长，限制 token 节省费用
            streaming=False,    # 非流式，等待结果后再继续
        )

        # ---- Embedding 模型：将文本转换为向量 ----
        # 与 document_service 中使用相同的模型，确保向量空间一致
        # （检索时的向量必须与存储时的向量在同一个空间才能正确比对）
        self.embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL_NAME,
            openai_api_key=settings.EMBEDDING_API_KEY,
            openai_api_base=settings.EMBEDDING_BASE_URL,
        )

    # --------------------------------------------------
    # 私有方法：同步操作（通过 asyncio.to_thread 在线程池运行）
    # --------------------------------------------------

    @property
    def _sync_db_url(self) -> str:
        """PGVector 需要 psycopg3 同步连接字符串（不能用 asyncpg）"""
        return settings.DATABASE_URL.replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg://",
        )

    def _get_retriever_sync(self, kb_id: int):
        """
        【同步方法，通过 asyncio.to_thread 调用】

        创建 PGVector 检索器。
        PGVector.as_retriever() 返回一个 VectorStoreRetriever 对象，
        调用 .get_relevant_documents(query) 时会：
          1. 对 query 调用 Embedding API 得到查询向量
          2. 在 pgvector 中执行 ANN 搜索（余弦相似度）
          3. 返回 top-k 个最相关的 LangchainDocument

        search_kwargs={"k": 3}：
          k=3 表示每次检索返回 3 个最相关片段
          数量越多上下文越丰富，但 token 消耗更多
          对于 500 字/chunk 的分块大小，k=3 约占 1500 字，合理
        """
        vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name=f"kb_{kb_id}",  # 每个知识库独立的 collection
            connection=self._sync_db_url,
            use_jsonb=True,
        )
        # as_retriever() 将 VectorStore 转换为 LangChain 的 BaseRetriever 接口
        # 统一了各种向量库的检索 API（Pinecone、Chroma、PGVector 等均可互换）
        return vector_store.as_retriever(
            search_type="similarity",       # 相似度检索（默认），也可以是 "mmr"（最大边际相关）
            search_kwargs={"k": 3},         # 返回 3 个最相关片段
        )

    def _retrieve_docs_sync(self, question: str, kb_id: int) -> list:
        """
        【同步方法，通过 asyncio.to_thread 调用】

        执行向量检索，返回 LangchainDocument 列表。
        每个 Document 包含：
          .page_content：文本内容
          .metadata：{"doc_id": 1, "filename": "xx.pdf", "chunk_index": 3, ...}
        """
        retriever = self._get_retriever_sync(kb_id)
        # get_relevant_documents 是同步阻塞调用：
        #   1. 内部调用 self.embeddings.embed_query(question) → 网络 I/O
        #   2. 在 pgvector 中执行 SQL 查询 → DB I/O
        docs = retriever.get_relevant_documents(question)
        logger.info(f"向量检索完成：问题='{question[:30]}...'，命中 {len(docs)} 个片段")
        return docs

    # --------------------------------------------------
    # 私有方法：数据格式转换（纯内存操作，无 I/O）
    # --------------------------------------------------

    def _to_history_tuples(self, chat_history: list[dict]) -> list[tuple[str, str]]:
        """
        将 DB/Redis 格式的消息列表转换为 (user, assistant) 元组列表。

        ConversationalRetrievalChain 的 chat_history 参数接受此格式。

        输入：[
            {"role": "user", "content": "苹果是什么？"},
            {"role": "assistant", "content": "苹果是一种水果。"},
        ]
        输出：[("苹果是什么？", "苹果是一种水果。")]

        注意：成对配对，奇数条消息的最后一条 user 消息会被丢弃
        （理论上不会发生，因为每个 user 消息后都有 assistant 回复）
        """
        tuples: list[tuple[str, str]] = []
        i = 0
        while i + 1 < len(chat_history):
            cur = chat_history[i]
            nxt = chat_history[i + 1]
            if cur.get("role") == "user" and nxt.get("role") == "assistant":
                tuples.append((cur["content"], nxt["content"]))
                i += 2
            else:
                i += 1  # 跳过格式不正确的消息
        return tuples

    def _format_history_str(self, history_tuples: list[tuple[str, str]]) -> str:
        """
        将 (user, assistant) 元组列表格式化为可读的文字，注入到 Prompt 的 {chat_history} 中。

        输出示例：
          用户：苹果是什么？
          助手：苹果是一种水果。

          用户：它有几种颜色？
          助手：苹果有红色、绿色和黄色。
        """
        if not history_tuples:
            return "（暂无历史对话）"

        lines = []
        for human, ai in history_tuples:
            lines.append(f"用户：{human}")
            lines.append(f"助手：{ai}")
        return "\n".join(lines)

    def _build_context(self, source_docs: list) -> str:
        """
        将检索到的 LangchainDocument 列表格式化为上下文字符串，
        注入到 Prompt 的 {context} 中。

        格式示例：
          【来源：产品手册.pdf | 第 3 块】
          苹果手机的电池容量为 3279 mAh...

          【来源：FAQ.txt | 第 7 块】
          充电时间约为 1.5 小时...

        每段文档之间用空行分隔，方便 LLM 识别边界。
        """
        if not source_docs:
            return "（未检索到相关文档内容）"

        parts = []
        for doc in source_docs:
            filename = doc.metadata.get("filename", "未知文件")
            chunk_idx = doc.metadata.get("chunk_index", "?")
            header = f"【来源：{filename} | 第 {chunk_idx} 块】"
            parts.append(f"{header}\n{doc.page_content.strip()}")

        return "\n\n".join(parts)

    def _format_source_docs(self, source_docs: list) -> list[dict]:
        """
        将 LangchainDocument 列表转换为可序列化的字典列表，
        用于存入数据库和返回给前端。

        返回格式：[
            {
                "doc_id": 1,
                "filename": "产品手册.pdf",
                "chunk_index": 3,
                "content": "苹果手机的电池容量...",
                "score": null   # 此处 get_relevant_documents 不返回 score
            }
        ]
        """
        return [
            {
                "doc_id": doc.metadata.get("doc_id"),
                "filename": doc.metadata.get("filename", "未知文件"),
                "chunk_index": doc.metadata.get("chunk_index", 0),
                "content": doc.page_content[:300],  # 截取前 300 字，避免存储过多
            }
            for doc in source_docs
        ]

    def _convert_history_to_messages(self, chat_history: list[dict]) -> list[BaseMessage]:
        """
        将消息字典列表转换为 LangChain BaseMessage 列表。
        供其他模块调用（如需直接传入 LangChain 链）。

        {"role": "user", "content": "..."} → HumanMessage(content="...")
        {"role": "assistant", "content": "..."} → AIMessage(content="...")
        """
        messages: list[BaseMessage] = []
        for msg in chat_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            # system 角色消息跳过（不作为对话历史传入）
        return messages

    # --------------------------------------------------
    # 核心步骤：问题浓缩
    # --------------------------------------------------

    async def _condense_question(
        self,
        question: str,
        chat_history: list[dict],
    ) -> str:
        """
        步骤①：问题浓缩（Condense Question）。

        如果没有历史对话，直接返回原问题（无需浓缩）。
        如果有历史，调用 condense_llm 改写问题为独立问题。

        示例：
          历史：用户问了"苹果是什么"，AI 回答了"苹果是水果"
          新问题："它有几种颜色？"
          浓缩后："苹果有几种颜色？"

        这一步很重要：向量检索时用"苹果有几种颜色"
        比"它有几种颜色"能找到更准确的文档片段。
        """
        history_tuples = self._to_history_tuples(chat_history)

        if not history_tuples:
            # 没有历史，第一轮对话，直接用原问题检索即可
            return question

        # 格式化历史为字符串
        history_str = self._format_history_str(history_tuples)

        # 构建浓缩链：CONDENSE_QUESTION_PROMPT | condense_llm | StrOutputParser
        # 这是 LangChain 的 LCEL（LangChain Expression Language）管道语法：
        #   | 操作符将多个 Runnable 连接成链，前一个的输出作为后一个的输入
        #   PromptTemplate.invoke({...}) → 生成格式化的提示词字符串
        #   condense_llm.invoke(提示词字符串) → 返回 AIMessage 对象
        #   StrOutputParser().invoke(AIMessage) → 提取纯文本字符串
        condense_chain = CONDENSE_QUESTION_PROMPT | self.condense_llm | StrOutputParser()

        # ainvoke 是异步版本的 invoke，不阻塞事件循环
        standalone_question = await condense_chain.ainvoke({
            "question": question,
            "chat_history": history_str,
        })

        standalone_question = standalone_question.strip()
        logger.info(f"问题浓缩：'{question[:30]}' → '{standalone_question[:30]}'")
        return standalone_question

    # --------------------------------------------------
    # 公开异步接口
    # --------------------------------------------------

    async def generate_answer(
        self,
        question: str,
        kb_id: int,
        chat_history: list[dict],
    ) -> tuple[str, list[dict]]:
        """
        非流式 RAG 问答：完整执行三步链路，等待所有结果后一次性返回。

        参数：
          question     : 用户当前问题
          kb_id        : 在哪个知识库中检索
          chat_history : 历史消息列表（已经过窗口限制）

        返回：(AI 回复的完整文本, 引用的文档片段列表)
        """
        # ---- 步骤①：浓缩问题 ----
        standalone_question = await self._condense_question(question, chat_history)

        # ---- 步骤②：向量检索（同步操作，放入线程池）----
        source_docs = await asyncio.to_thread(
            self._retrieve_docs_sync, standalone_question, kb_id
        )

        # ---- 步骤③：构建 Prompt 并调用 LLM ----
        history_tuples = self._to_history_tuples(chat_history)
        context = self._build_context(source_docs)
        history_str = self._format_history_str(history_tuples)

        # format_messages 将模板变量替换为实际值，返回消息列表
        messages = QA_PROMPT.format_messages(
            context=context,
            chat_history=history_str,
            question=question,        # 注意：这里用原始问题（浓缩问题用于检索）
        )

        # ainvoke 异步调用 LLM，等待完整回复
        response = await self.llm.ainvoke(messages)

        # 格式化来源文档为可序列化格式
        sources = self._format_source_docs(source_docs)

        logger.info(
            f"非流式 RAG 完成：问题='{question[:20]}'，"
            f"检索 {len(source_docs)} 篇，回复 {len(response.content)} 字"
        )
        return response.content, sources

    async def generate_answer_stream(
        self,
        question: str,
        kb_id: int,
        chat_history: list[dict],
    ) -> AsyncIterator[dict]:
        """
        流式 RAG 问答：前两步同步执行，第三步逐 token 异步生成。

        使用 ChatOpenAI.astream() 实现流式输出（LangChain 原生支持）：
          - 底层通过 OpenAI 的 stream=True 参数开启 SSE 流
          - 每收到一个 token 就 yield 给调用方
          - 不需要等所有 token 生成完毕才能开始展示

        yield 格式：
          {"type": "token",   "content": "苹"}         每个 token
          {"type": "sources", "sources": [...]}         所有 token 结束后
        """
        # ---- 步骤①：浓缩问题（非流式，等待结果后继续）----
        standalone_question = await self._condense_question(question, chat_history)

        # ---- 步骤②：向量检索（同步，线程池）----
        source_docs = await asyncio.to_thread(
            self._retrieve_docs_sync, standalone_question, kb_id
        )

        # ---- 步骤③：流式生成答案 ----
        history_tuples = self._to_history_tuples(chat_history)
        context = self._build_context(source_docs)
        history_str = self._format_history_str(history_tuples)

        messages = QA_PROMPT.format_messages(
            context=context,
            chat_history=history_str,
            question=question,
        )

        # astream() 返回一个异步生成器，每次 yield 一个 AIMessageChunk
        # AIMessageChunk.content 就是当前 token 的文本（可能是单字或多字）
        async for chunk in self.llm.astream(messages):
            token_text = chunk.content
            if token_text:  # 过滤空 token（流开始/结束时可能有空字符串）
                yield {"type": "token", "content": token_text}

        # 所有 token 生成完毕后，发送来源文档信息
        # 注意：sources 是在检索阶段（步骤②）就已经得到的，不需要等 LLM 结束
        yield {
            "type": "sources",
            "sources": self._format_source_docs(source_docs),
        }

        logger.info(
            f"流式 RAG 完成：问题='{question[:20]}'，"
            f"检索 {len(source_docs)} 篇文档片段"
        )

    async def get_question_embedding(self, question: str) -> list[float]:
        """
        获取问题文本的 Embedding 向量。

        供语义缓存模块调用：
          1. 查询语义缓存前，需要先把用户问题转成向量
          2. 缓存未命中后，把这个向量存入语义缓存供后续比对
          3. 不用单独调用 Embedding API，复用 self.embeddings 实例

        OpenAIEmbeddings.aembed_query()：
          - 异步版本的 embed_query（langchain_openai 0.3+ 支持）
          - 内部调用 Embedding API，返回 list[float]
          - 向量维度由 EMBEDDING_MODEL_NAME 决定（智谱 embedding-3 → 2048 维）

        与 RAG 检索的关系：
          RAG 的 _retrieve_docs_sync 内部也会对问题做一次 Embedding，
          目前存在一次重复计算。未来优化可将此处得到的向量直接
          传给检索步骤，避免重复网络请求（TODO: 优化点）。
        """
        try:
            # aembed_query 是异步方法，直接 await，不需要 to_thread
            embedding: list[float] = await self.embeddings.aembed_query(question)
            logger.debug(
                f"问题 Embedding 计算完成：'{question[:30]}'，"
                f"维度={len(embedding)}"
            )
            return embedding
        except Exception as e:
            logger.error(f"问题 Embedding 计算失败：{e}")
            # 返回空列表，调用方（redis_service）会跳过语义缓存检查
            return []


# 全局 RAG 服务单例
rag_service = RAGService()
