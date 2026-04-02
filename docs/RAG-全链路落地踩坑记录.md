# RAG 全链路落地踩坑记录

本文基于 [ai-chat-rag](.) 项目从「文档上传 → 解析 → 分块 → 向量化 → 检索 → 生成」的完整落地过程，总结一批真实踩过的坑和对应做法，方便复现或二次开发时少走弯路。

---

## 一、整体链路回顾

```
上传文件 → 解析文本 → 分块(Chunk) → Embedding → 写入 pgvector
                                                      ↓
用户提问 → 问题浓缩(Condense) → 向量检索 → 拼 Context + 历史 → LLM 生成 → 流式输出
```

- **摄入侧**：`document_service` 负责解析、分块、向量化、按知识库写入 PGVector。
- **检索侧**：`rag_service` 负责问题浓缩、检索、拼 Prompt、调用 LLM；支持流式且把 `chat_history` 和 `context` 一起塞进最终 QA。

下面按环节说坑和解决方案。

---

## 二、文档解析

### 2.1 PDF 用谁解析

- **pypdf / PyPDF2**：提取快，但对多栏、表格、扫描版支持一般，容易乱序。
- **pdfplumber**：基于 pdfminer，对表格和多栏排版更友好，本项目选用。

```python
# backend/services/document_service.py 中
if file_ext == ".pdf":
    raw_text = await asyncio.to_thread(self._extract_text_from_pdf, file_content)
```

**坑**：PDF 解析是 **CPU/IO 密集**，若在主线程同步跑会卡住整个事件循环。必须用 `asyncio.to_thread()` 丢到线程池。

**坑**：纯图片 PDF 没有文字层，`extract_text()` 会得到空字符串。需要在解析后判断 `if not raw_text.strip()` 并明确报错或标记「需 OCR」。

---

## 三、分块 (Chunking)

### 3.1 分块器与参数

项目用 LangChain 的 `RecursiveCharacterTextSplitter`，`chunk_size=500`、`chunk_overlap=50`（来自 `config`）。

```python
# document_service.py
self.text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.CHUNK_SIZE,
    chunk_overlap=settings.CHUNK_OVERLAP,
    length_function=len,
    add_start_index=True,
    separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
)
```

**坑**：默认 `separators` 偏英文，中文长段会先在 `". "` 切，容易把一句中文从中间切开。建议把中文句号、问号、感叹号放在前面，如上所示。

**坑**：`chunk_size` 按「字符」算，不是 token。若后续用按 token 计费的模型，需要心里有数：500 字符约 200–300 token（中英混合）。过大会导致单次检索 token 过多，过小则语义碎片化。

### 3.2 元数据必须带齐

每个 chunk 的 `metadata` 里建议带上：`doc_id`、`filename`、`chunk_index`、`kb_id`。这样：

- 删除文档时能按 `doc_id` 删光该文档在向量库里的所有 chunk；
- 前端可以展示「来源：xx.pdf 第 3 块」。

PGVector（langchain-postgres）用 JSONB 存 metadata，查询、删除都靠这些字段，一开始没带后面很难补。

---

## 四、向量化与存储

### 4.1 Embedding 与 PGVector 都是同步的

LangChain 的 `OpenAIEmbeddings` 和 `PGVector.add_documents()` 底层都是同步调用（请求 API + 写 DB）。若在 async 接口里直接 `await embeddings.aembed_documents(...)` 有的版本有，但 PGVector 常用的是同步 `add_documents`。

**做法**：统一用 `asyncio.to_thread()` 包一层，避免阻塞事件循环：

```python
await asyncio.to_thread(
    self._add_documents_to_vectorstore_sync, chunks, kb_id
)
```

### 4.2 数据库连接字符串两套

- **业务 ORM**：SQLAlchemy + asyncpg，连接串形如 `postgresql+asyncpg://...`
- **PGVector / langchain-postgres**：底层是 **psycopg3 同步**，要 `postgresql+psycopg://...`

**坑**：直接拿 async 的 URL 给 PGVector 会报错或连不上。项目里在 `rag_service` 和 `document_service` 都做了转换：

```python
def _sync_db_url(self) -> str:
    return settings.DATABASE_URL.replace(
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
    )
```

### 4.3 按知识库隔离 collection

每个知识库一个 collection（如 `kb_{kb_id}`），检索时只在该知识库下搜，避免跨库污染。创建/删除知识库时要对应创建/清理 collection 或表数据。

---

## 五、检索与 RAG 三步

### 5.1 问题浓缩 (Condense)

多轮里用户常问「那它的价格呢？」这类依赖上文的问题，直接拿去做向量检索效果差。需要先浓缩成「XX 产品的价格是多少？」这种独立问题。

**实现**：单独一个 Prompt + 非流式 LLM 调用，把 `chat_history` 和当前 `question` 丢进去，得到 `standalone_question` 再去做检索。本项目等价于 LangChain 的 `ConversationalRetrievalChain` 的 condense 步骤，但自己写以便控制传入最终 QA 的内容。

### 5.2 检索用同步方法 + to_thread

`retriever.get_relevant_documents(question)` 内部会调 Embedding 和 PG，都是同步的，同样要放到线程里：

```python
source_docs = await asyncio.to_thread(
    self._retrieve_docs_sync, standalone_question, kb_id
)
```

### 5.3 最终 QA 要同时拿到 context 和 chat_history

LangChain 的 `ConversationalRetrievalChain` 默认不会把「历史对话」传给最后一步的 combine_docs chain，只传检索到的 context。若产品要求「结合上文回答」，就需要自己拆三步，在最终 Prompt 里同时注入 `context` 和 `chat_history`。这是本项目手写 RAG 链的主要原因之一。

---

## 六、流式输出

### 6.1 先流 token，最后再给 sources

用户期望先看到答案逐字出来，再看到引用来源。做法是：用 `llm.astream(messages)` 先逐 chunk 把 `content` 推给前端，流结束后再发一条 `type: "sources"` 的事件带上 `source_docs`，前端先渲染回答，再在底部展示来源。

### 6.2 代理与缓冲

若经过反向代理（或任意中间层），流式响应可能被缓冲，导致前端不是「逐字」而是「整段」才出来。应对方式是对承载 SSE 的路径关闭响应缓冲。本仓库在生产镜像的 `frontend/nginx.conf` 里已对 `/api/v1/chat/stream` 设置 `proxy_buffering off` 等；若你自行再加一层代理，同样需要在该层关闭缓冲，例如：

```
proxy_buffering off;
proxy_cache off;
```

---

## 七、删除文档与向量

langchain-postgres 的 `PGVector.delete()` 常见用法是按向量 ID 删，不直接支持「按 metadata.doc_id 删」。项目里的做法是：直接写 SQL 查 `langchain_pg_collection` 拿到 collection 的 UUID，再在 `langchain_pg_embedding` 里用 JSONB 条件（如 `metadata->>'doc_id' = :doc_id`）批量删除，比先 similarity_search 再按 ID 删更可靠，且不受 top_k 限制。

---

## 八、性能与稳定性

当前项目保持最简 RAG 路线，不额外引入缓存层。性能优化重点放在：

- 检索片段数（`top_k`）和分块参数（`chunk_size/chunk_overlap`）的平衡；
- 流式输出体验和代理层缓冲配置；
- Embedding/LLM API 稳定性与超时重试策略。

---

## 九、小结

| 环节     | 坑点摘要                               | 建议做法                                           |
|----------|----------------------------------------|----------------------------------------------------|
| 解析     | PDF 阻塞事件循环；纯图 PDF 无文字      | `asyncio.to_thread`；空文本检测/OCR 提示           |
| 分块     | 中文被错误分隔；chunk 过大/过小        | 中文标点优先 separators；按 token 粗算 size        |
| 元数据   | 少带 doc_id/kb_id 导致难删、难展示来源 | 每个 chunk 必带 doc_id、filename、chunk_index、kb_id |
| 向量/DB  | 同步调用卡 async；PG 连接串不一致       | Embedding/PGVector 全用 to_thread；sync URL 单独一份 |
| 检索     | 多轮问句直接检索效果差                 | 先 Condense 再 Retrieve                            |
| QA Prompt| 历史传不进最后一步                     | 手写三步，最终 Prompt 里同时传 context + chat_history |
| 流式     | 代理缓冲导致不逐字                     | 对 SSE 路径关 buffering（参见 `frontend/nginx.conf`）；外加代理时同步配置 |
| 删文档   | 按 metadata 批量删                     | 直接 SQL 按 JSONB doc_id 删 embedding 表          |

以上都来自当前仓库的真实实现，代码位置可参考 `backend/services/document_service.py` 和 `backend/services/rag_service.py`。若你也在做 RAG 全链路，希望这篇能帮你少踩一遍坑。
