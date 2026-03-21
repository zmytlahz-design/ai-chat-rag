# ==================================================
# 文档处理服务（完整实现）
# 处理链路：上传文件 → 解析文本 → 切分 Chunk → Embedding → 存入 pgvector
#
# 关键设计：
#   1. 所有阻塞操作（pdfplumber / Embedding API / DB写入）
#      用 asyncio.to_thread() 包裹，放入线程池执行，不阻塞事件循环
#   2. 每个 chunk 都携带 metadata：doc_id / filename / chunk_index
#      方便后续按文档删除向量、展示引用来源
#   3. 每个知识库用独立的 PGVector collection（kb_{kb_id}），逻辑隔离
# ==================================================

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import pdfplumber
# pdfplumber：基于 pdfminer.six 的 PDF 解析库
# 优点：能正确处理多栏排版、表格，比 pypdf 文本提取更准确
# open() → 返回 PDF 对象，pages 属性为页面列表，page.extract_text() 提取文本

from langchain.schema import Document as LangchainDocument
# LangchainDocument：LangChain 的文档单元
# 包含两个字段：
#   page_content (str)：文本内容
#   metadata (dict)：附属元数据，自由定义键值

from langchain.text_splitter import RecursiveCharacterTextSplitter
# RecursiveCharacterTextSplitter：递归字符分割器
# 分割策略：依次尝试 ["\n\n", "\n", "。", ".", " ", ""] 作为分割符
# 先用段落分，分不下去再用换行，以此类推，尽量保持语义完整

from langchain_openai import OpenAIEmbeddings
# OpenAIEmbeddings：LangChain 的 OpenAI Embedding 适配器
# 通过 openai_api_base 可以对接任何兼容 OpenAI 格式的 Embedding 服务
# 例如：智谱 AI embedding-3、OpenAI 官方或其他 OpenAI 兼容 Embedding 端点

from langchain_postgres import PGVector
# PGVector：LangChain 官方的 pgvector 向量存储集成
# 底层依赖 psycopg3（同步）连接 PostgreSQL
# 会自动创建两张表：
#   langchain_pg_collection：存储 collection 名称与 UUID 映射
#   langchain_pg_embedding：存储向量数据和 JSONB 元数据
from sqlalchemy import text

from config import settings
from database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# 支持的文件扩展名集合（小写）
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}

# 上传文件大小上限：50 MB（字节）
MAX_FILE_SIZE = 50 * 1024 * 1024


class DocumentService:
    """
    文档处理服务。
    对外暴露三个公开异步方法：
      - process_document()：完整处理一个文档
      - delete_document_vectors()：按 doc_id 删除向量
      - search_similar_chunks()：相似度检索
    """

    def __init__(self):
        # ---- 文本分割器 ----
        # chunk_size=500 表示每块最多 500 个字符
        # chunk_overlap=50 表示相邻块重叠 50 字符，避免语义在边界断裂
        # add_start_index=True 会在 metadata 里加入 start_index 字段（该 chunk 在原文的起始位置）
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            length_function=len,
            add_start_index=True,
            # 中文文档优先按段落、句子分割，增加中文标点
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )

        # ---- Embedding 模型 ----
        # openai_api_key / openai_api_base：兼容任意 OpenAI 格式的 Embedding 服务
        # 智谱 AI：base_url = https://open.bigmodel.cn/api/paas/v4，model = embedding-3
        # 亦可使用本地向量模型（如 text2vec）自建兼容端点
        self.embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL_NAME,
            openai_api_key=settings.EMBEDDING_API_KEY,
            openai_api_base=settings.EMBEDDING_BASE_URL,
        )

    # --------------------------------------------------
    # 私有辅助方法
    # --------------------------------------------------

    @property
    def _sync_db_url(self) -> str:
        """
        将异步连接字符串转换为 psycopg3 同步连接字符串。
        langchain_postgres.PGVector 底层使用 psycopg3 同步模式，
        不能用 asyncpg，所以需要替换驱动前缀。
        原：postgresql+asyncpg://user:pass@host:5432/db
        改：postgresql+psycopg://user:pass@host:5432/db
        """
        return settings.DATABASE_URL.replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg://",
        )

    def _get_vector_store(self, kb_id: int) -> PGVector:
        """
        获取指定知识库的 PGVector 实例。
        每次调用都会新建一个实例（因为是在线程里执行，线程安全）。

        collection_name = "kb_{kb_id}"
          - 每个知识库一个 collection，逻辑上完全隔离
          - 同一张 langchain_pg_embedding 表，通过 collection_id 区分
        """
        return PGVector(
            embeddings=self.embeddings,
            collection_name=f"kb_{kb_id}",
            connection=self._sync_db_url,
            use_jsonb=True,             # metadata 用 JSONB 存储，支持索引查询
            pre_delete_collection=False, # 不在初始化时清空 collection
        )

    # ---- 文件解析 ----

    def _extract_text_from_pdf(self, file_content: bytes) -> str:
        """
        用 pdfplumber 解析 PDF，提取所有页面的文本。
        使用临时文件是因为 pdfplumber.open() 需要文件路径或文件对象，
        而我们收到的是 bytes，先写入临时文件再解析。

        每页文本前加上 "[第 N 页]" 标记，方便后续定位引用来源。
        """
        # 创建临时文件（suffix=".pdf" 让 pdfplumber 能识别格式）
        # delete=False：先不删除，等处理完后手动删除
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            text_parts = []
            with pdfplumber.open(tmp_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"PDF 共 {total_pages} 页，开始提取文本...")

                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        # 每页文本加上页码标记，便于溯源
                        text_parts.append(f"[第 {page_num} 页]\n{page_text.strip()}")

            if not text_parts:
                raise ValueError(
                    "PDF 文本提取结果为空。"
                    "可能是扫描版 PDF（图片），请先进行 OCR 处理后再上传。"
                )

            # 各页文本用双换行连接，让分割器能识别页面边界
            return "\n\n".join(text_parts)

        finally:
            # 无论成功还是失败，都要删除临时文件，防止磁盘泄漏
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _extract_text_from_txt_md(self, file_content: bytes) -> str:
        """
        直接解码 TXT / MD 文件内容。
        按顺序尝试 UTF-8 → GBK → Latin-1，兼容不同系统生成的文件。
        GBK 用于兼容 Windows 中文环境下保存的文件。
        """
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                text = file_content.decode(encoding)
                logger.debug(f"文件使用 {encoding} 编码解码成功")
                return text
            except UnicodeDecodeError:
                continue

        raise ValueError(
            "文件编码无法识别，请将文件转存为 UTF-8 编码后重新上传。"
        )

    # ---- 文本分块 ----

    def _split_text_into_chunks(
        self,
        raw_text: str,
        doc_id: int,
        filename: str,
        kb_id: int,
    ) -> list[LangchainDocument]:
        """
        将原始文本切分为 chunks，并为每个 chunk 附加元数据。

        元数据字段说明：
          doc_id       (int)  ：对应 documents 表的主键，方便按文档删除向量
          filename     (str)  ：原始文件名，用于在回答中展示"来自 XX.pdf"
          chunk_index  (int)  ：该 chunk 在文档中的序号（从 0 开始）
          kb_id        (int)  ：所属知识库，冗余存储便于按知识库直接过滤
          start_index  (int)  ：由 text_splitter 自动添加，chunk 在原文的字符偏移

        注意：metadata 的 value 必须是 JSON 可序列化的基础类型（str / int / float / bool）。
        """
        # split_text() 返回纯字符串列表
        raw_chunks: list[str] = self.text_splitter.split_text(raw_text)

        documents = []
        for idx, chunk_text in enumerate(raw_chunks):
            doc = LangchainDocument(
                page_content=chunk_text,
                metadata={
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": idx,
                    "kb_id": kb_id,
                },
            )
            documents.append(doc)

        logger.info(
            f"文档 doc_id={doc_id} 共切分为 {len(documents)} 个 chunk "
            f"（chunk_size={settings.CHUNK_SIZE}, overlap={settings.CHUNK_OVERLAP}）"
        )
        return documents

    # ---- 向量化存储（同步，在线程池中运行）----

    def _add_documents_to_vectorstore_sync(
        self,
        documents: list[LangchainDocument],
        kb_id: int,
    ) -> None:
        """
        【同步方法，通过 asyncio.to_thread 在线程池中调用】

        将 chunks 批量向量化并写入 pgvector。
        流程：
          1. add_documents() 内部调用 embeddings.embed_documents() 批量获取向量
          2. 将 (向量, 原文, metadata) 批量 INSERT 到 langchain_pg_embedding 表

        注意：此方法同时触发网络 I/O（调用 Embedding API）和 DB I/O，
        耗时可能较长（取决于 chunk 数量和网络延迟），必须放在线程池中执行。
        """
        vector_store = self._get_vector_store(kb_id)
        # add_documents 内部会自动分批，避免单次请求 token 超限
        vector_store.add_documents(documents)
        logger.info(f"知识库 kb_{kb_id} 成功写入 {len(documents)} 个向量")

    def _search_sync(
        self,
        query: str,
        kb_id: int,
        top_k: int,
    ) -> list[tuple[LangchainDocument, float]]:
        """
        【同步方法，通过 asyncio.to_thread 在线程池中调用】

        执行相似度搜索，返回 (LangchainDocument, score) 的列表。
        score 是余弦相似度（0～1，越接近 1 越相关）。
        """
        vector_store = self._get_vector_store(kb_id)
        # similarity_search_with_relevance_scores：返回文档和相关性得分
        # 内部先对 query 做 Embedding，再在 pgvector 中做 ANN（近似最近邻）搜索
        return vector_store.similarity_search_with_relevance_scores(query, k=top_k)

    # --------------------------------------------------
    # 公开异步接口
    # --------------------------------------------------

    async def process_document(
        self,
        file_content: bytes,
        filename: str,
        kb_id: int,
        doc_id: int,
    ) -> int:
        """
        完整处理一个文档：解析 → 分块 → 向量化 → 存储。
        返回成功写入的 chunk 数量。

        所有阻塞操作（PDF 解析、Embedding API 调用）都通过
        asyncio.to_thread() 丢给线程池，不阻塞 FastAPI 的异步事件循环。

        参数：
          file_content : 文件二进制内容（由 UploadFile.read() 读取）
          filename     : 原始文件名，用于判断文件类型和存入 metadata
          kb_id        : 目标知识库 ID
          doc_id       : documents 表中的主键（需先插入记录再调用此方法）
        """
        file_ext = Path(filename).suffix.lower()

        if file_ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"不支持的文件类型 '{file_ext}'，"
                f"当前支持：{', '.join(SUPPORTED_EXTENSIONS)}"
            )

        # ---- 步骤 1：解析文件（CPU / I/O 密集，放入线程池）----
        logger.info(f"开始解析文档 doc_id={doc_id}，文件名：{filename}")

        if file_ext == ".pdf":
            # pdfplumber.open() 是同步阻塞调用，必须用 to_thread 包裹
            raw_text = await asyncio.to_thread(
                self._extract_text_from_pdf, file_content
            )
        else:
            # TXT / MD 解码是 CPU 操作，但为统一风格也走线程池
            raw_text = await asyncio.to_thread(
                self._extract_text_from_txt_md, file_content
            )

        if not raw_text.strip():
            raise ValueError("解析结果为空，文档可能是空文件或纯图片 PDF。")

        logger.info(f"doc_id={doc_id} 解析完成，文本长度 {len(raw_text)} 字符")

        # ---- 步骤 2：文本分块（纯 CPU 操作，速度快，可在主线程执行）----
        # split_text 是纯字符串操作，不涉及 I/O，直接在事件循环中运行即可
        chunks = self._split_text_into_chunks(raw_text, doc_id, filename, kb_id)

        if not chunks:
            raise ValueError("文本分块结果为空，请检查文档内容是否过短。")

        # ---- 步骤 3：向量化 + 存入 pgvector（网络 I/O，放入线程池）----
        # _add_documents_to_vectorstore_sync 内部会：
        #   a) 调用 Embedding API（网络请求，耗时主要在这里）
        #   b) 将结果 INSERT 到 PostgreSQL
        logger.info(f"doc_id={doc_id} 开始向量化，共 {len(chunks)} 个 chunk...")
        await asyncio.to_thread(
            self._add_documents_to_vectorstore_sync, chunks, kb_id
        )

        logger.info(f"doc_id={doc_id} 向量化完成，共写入 {len(chunks)} 个向量")
        return len(chunks)

    async def delete_document_vectors(self, kb_id: int, doc_id: int) -> None:
        """
        从 pgvector 删除指定文档的所有向量。

        实现思路：
          langchain_postgres.PGVector.delete() 只支持按 UUID 删除，
          不支持按 metadata 字段过滤，因此我们直接操作底层数据表：
            1. 查 langchain_pg_collection 表获取 collection UUID
            2. 用 JSONB 操作符 (->>)  按 doc_id 字段过滤删除

          这比先 similarity_search 查出所有 ID 再删除要高效得多，
          且不受 top_k 限制（文档可能有几百个 chunk）。
        """
        collection_name = f"kb_{kb_id}"

        async with AsyncSessionLocal() as session:
            # ---- 第一步：查出 collection 的 UUID ----
            # langchain_pg_collection 表结构：
            #   uuid (UUID, PK) | name (TEXT) | cmetadata (JSONB)
            result = await session.execute(
                text(
                    "SELECT uuid FROM langchain_pg_collection WHERE name = :name"
                ),
                {"name": collection_name},
            )
            row = result.fetchone()

            if row is None:
                # collection 还不存在（该知识库从未写入过向量），直接返回
                logger.warning(
                    f"向量集合 '{collection_name}' 不存在，跳过向量删除。"
                )
                return

            collection_uuid = str(row[0])

            # ---- 第二步：按 doc_id 过滤删除 ----
            # langchain_pg_embedding 表结构：
            #   id (UUID, PK) | collection_id (UUID, FK) | embedding (vector) |
            #   document (TEXT) | cmetadata (JSONB)
            #
            # cmetadata->>'doc_id' 用 ->> 操作符提取 JSONB 中 doc_id 的文本值
            # 存入时 doc_id 是整数，JSONB 里存为数字，->> 提取后是字符串
            # 所以 :doc_id 参数要传字符串类型
            delete_result = await session.execute(
                text(
                    """
                    DELETE FROM langchain_pg_embedding
                    WHERE collection_id = :collection_id
                      AND cmetadata->>'doc_id' = :doc_id
                    """
                ),
                {
                    "collection_id": collection_uuid,
                    "doc_id": str(doc_id),   # JSONB 文本提取后是字符串
                },
            )
            await session.commit()

            deleted_count = delete_result.rowcount
            logger.info(
                f"已从集合 '{collection_name}' 删除 doc_id={doc_id} "
                f"的 {deleted_count} 条向量记录"
            )

    async def search_similar_chunks(
        self,
        query: str,
        kb_id: int,
        top_k: int = 5,
    ) -> list[dict]:
        """
        相似度检索：根据问题文本，从指定知识库中找出最相关的 top_k 个文本块。
        这是 RAG 流程的"R"（Retrieval）部分，是生成高质量答案的关键。

        内部流程：
          1. 对 query 调用 Embedding API，得到查询向量
          2. 在 pgvector 中执行 ANN（近似最近邻）搜索（使用余弦相似度）
          3. 返回 top_k 个最相似的文本块及其得分

        返回格式：
          [
            {
              "content": "...文本内容...",
              "doc_id": 1,
              "filename": "xxx.pdf",
              "chunk_index": 3,
              "score": 0.92   # 余弦相似度，越接近 1 越相关
            },
            ...
          ]
        """
        # _search_sync 内部先做 Embedding（网络 I/O），再查数据库（DB I/O）
        # 两者都是阻塞操作，放入线程池
        results: list[tuple[LangchainDocument, float]] = await asyncio.to_thread(
            self._search_sync, query, kb_id, top_k
        )

        return [
            {
                "content": doc.page_content,
                "doc_id": doc.metadata.get("doc_id"),
                "filename": doc.metadata.get("filename", "未知文件"),
                "chunk_index": doc.metadata.get("chunk_index", 0),
                "score": round(float(score), 4),  # 保留 4 位小数
            }
            for doc, score in results
        ]


# 全局单例：整个项目通过 from services.document_service import document_service 使用
document_service = DocumentService()
