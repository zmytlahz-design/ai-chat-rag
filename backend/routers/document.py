# ==================================================
# 文档路由模块（完整实现）
# 前缀：/api/v1/documents（在 main.py 中注册）
#
# 接口列表：
#   POST   /upload          上传文档（立即返回，后台异步处理向量化）
#   GET    /kb/{kb_id}      获取某知识库下的所有文档
#   GET    /{doc_id}        查询单个文档（用于轮询处理状态）
#   DELETE /{doc_id}        删除文档及其向量数据
#
# 异步上传设计：
#   上传文件后立即返回 status="pending" 的文档记录，
#   向量化在后台通过 FastAPI BackgroundTasks 异步执行。
#   前端可定期轮询 GET /{doc_id} 检查 status 字段：
#     pending     → 已接收，等待处理
#     processing  → 正在解析/向量化
#     completed   → 处理完成，可以开始对话
#     failed      → 处理失败，error_message 字段有详情
# ==================================================

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,  # FastAPI 内置后台任务调度器，响应发送后执行
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from models.document import Document
from models.knowledge_base import KnowledgeBase
from services.document_service import document_service, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================================================
# Pydantic Schema（请求/响应数据结构）
# ==================================================

class DocumentResponse(BaseModel):
    """文档信息响应体，对应 documents 表中一条记录"""
    id: int
    kb_id: int
    filename: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    chunk_count: int
    status: str         # pending / processing / completed / failed
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # from_attributes=True 允许直接从 SQLAlchemy ORM 对象构造此模型
    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    """文档列表响应体"""
    total: int = Field(description="该知识库下文档总数")
    items: list[DocumentResponse] = Field(description="文档列表（按上传时间倒序）")


# ==================================================
# 后台任务函数（模块级函数，不依赖请求上下文）
# ==================================================

async def _run_document_processing(
    doc_id: int,
    kb_id: int,
    file_content: bytes,
    filename: str,
) -> None:
    """
    文档后台处理任务。

    这个函数在 FastAPI 返回 HTTP 响应之后异步执行，
    因此不能复用请求中的数据库 session（那个 session 已经关闭了）。
    必须在这里自己创建新的 AsyncSession。

    执行流程：
      1. 更新 documents.status = 'processing'
      2. 调用 document_service.process_document()（耗时操作）
      3. 更新 status = 'completed'，写入 chunk_count
      如果任何一步出错：
      4. 更新 status = 'failed'，写入 error_message
    """
    logger.info(f"[后台任务] 开始处理 doc_id={doc_id}，文件：{filename}")

    # ---- 第一步：将状态更新为 processing ----
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            logger.error(f"[后台任务] doc_id={doc_id} 不存在，任务终止")
            return
        doc.status = "processing"
        doc.updated_at = datetime.utcnow()
        await db.commit()
        logger.info(f"[后台任务] doc_id={doc_id} 状态已更新为 processing")

    # ---- 第二步：执行文档处理（解析 / 分块 / 向量化）----
    try:
        chunk_count = await document_service.process_document(
            file_content=file_content,
            filename=filename,
            kb_id=kb_id,
            doc_id=doc_id,
        )

        # ---- 第三步：成功 → 更新为 completed ----
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = "completed"
                doc.chunk_count = chunk_count
                doc.updated_at = datetime.utcnow()
                await db.commit()
                logger.info(
                    f"[后台任务] doc_id={doc_id} 处理完成，"
                    f"共 {chunk_count} 个 chunk"
                )

    except Exception as e:
        # ---- 第四步：失败 → 更新为 failed，记录错误信息 ----
        logger.error(
            f"[后台任务] doc_id={doc_id} 处理失败：{e}",
            exc_info=True,   # 打印完整堆栈，方便排查
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = "failed"
                # error_message 字段最长 500 字符（对应数据库列定义）
                doc.error_message = str(e)[:500]
                doc.updated_at = datetime.utcnow()
                await db.commit()


# ==================================================
# 接口实现
# ==================================================

@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传文档到知识库",
    description="""
上传一个文档文件到指定知识库，支持 PDF / TXT / MD 格式。

**处理流程（异步）：**
1. 接口立即返回，`status` 字段为 `pending`
2. 后台异步执行：文件解析 → 文本分块 → Embedding 向量化 → 存入 pgvector
3. 前端轮询 `GET /{doc_id}` 查询 `status` 字段了解进度

**状态流转：** `pending` → `processing` → `completed` / `failed`
    """,
)
async def upload_document(
    background_tasks: BackgroundTasks,   # FastAPI 注入后台任务调度器
    kb_id: int = Form(..., description="目标知识库 ID，文档将归属到该知识库"),
    file: UploadFile = File(..., description="上传的文件，支持 PDF / TXT / MD"),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    上传文档接口。

    技术要点：
    - 文件通过 multipart/form-data 格式上传（前端 FormData）
    - 文件内容一次性读入内存（bytes），传给后台任务
    - 立即将文档记录写入数据库（status=pending），然后返回
    - 后台任务在响应发送后异步启动，不阻塞当前请求
    """

    # ---- 1. 校验知识库是否存在 ----
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = kb_result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"知识库 ID={kb_id} 不存在，请先创建知识库",
        )

    # ---- 2. 校验文件类型 ----
    filename = file.filename or "unknown"
    # Path().suffix 提取扩展名，如 ".pdf"，lower() 统一小写
    file_ext = Path(filename).suffix.lower() if filename != "unknown" else ""

    if file_ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"不支持的文件类型 '{file_ext}'，"
                f"目前支持：{', '.join(SUPPORTED_EXTENSIONS)}"
            ),
        )

    # ---- 3. 读取文件内容并校验大小 ----
    # UploadFile.read() 是异步方法，不阻塞事件循环
    file_content: bytes = await file.read()
    file_size = len(file_content)

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="上传的文件内容为空",
        )

    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小 {size_mb:.1f}MB 超过限制（最大 {max_mb:.0f}MB）",
        )

    # ---- 4. 在数据库中创建文档记录（status=pending）----
    doc = Document(
        kb_id=kb_id,
        filename=filename,
        file_type=file_ext.lstrip("."),  # 去掉点，存 "pdf" 而不是 ".pdf"
        file_size=file_size,
        chunk_count=0,
        status="pending",
    )
    db.add(doc)
    # flush 将 INSERT 语句发送给数据库并获取自增 ID，
    # 但尚未 commit（事务还没结束），get_db 会在路由函数结束时 commit
    await db.flush()
    await db.refresh(doc)  # 刷新对象，获取数据库写入后的完整字段（如 created_at）

    logger.info(
        f"文档已入库：doc_id={doc.id}，filename={filename}，"
        f"kb_id={kb_id}，大小={file_size} 字节"
    )

    # ---- 5. 注册后台任务 ----
    # add_task() 在本次 HTTP 响应发送完毕后触发执行
    # 注意：file_content 是 bytes 副本，已从 UploadFile 中完整读出，
    # 后台任务可以安全使用（UploadFile 可能在响应后关闭）
    background_tasks.add_task(
        _run_document_processing,
        doc_id=doc.id,
        kb_id=kb_id,
        file_content=file_content,
        filename=filename,
    )

    logger.info(f"doc_id={doc.id} 后台处理任务已注册，即将返回响应")

    # 返回 status=pending 的文档记录，前端凭此 id 轮询进度
    return DocumentResponse.model_validate(doc)


@router.get(
    "/kb/{kb_id}",
    response_model=DocumentListResponse,
    summary="获取知识库下的所有文档",
    description="按上传时间倒序列出指定知识库的所有文档，支持分页。",
)
async def list_documents(
    kb_id: int,
    skip: int = 0,                          # 跳过前 skip 条（分页偏移量）
    limit: int = 20,                        # 每页返回数量（默认 20，最大 100）
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """
    获取指定知识库下的文档列表。

    路径参数 kb_id（而非查询参数）的设计原因：
      使用 /kb/{kb_id} 前缀与 /{doc_id} 路径区分开，
      避免 FastAPI 路由冲突（两个整数路径参数无法区分）。
    """
    # 限制 limit 上限，防止一次查询太多数据
    limit = min(limit, 100)

    # ---- 查总数 ----
    count_result = await db.execute(
        select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
    )
    total = count_result.scalar_one()

    # ---- 分页查询 ----
    # order_by(Document.created_at.desc())：按上传时间倒序，最新上传的在最前面
    docs_result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb_id)
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    docs = docs_result.scalars().all()

    return DocumentListResponse(
        total=total,
        items=[DocumentResponse.model_validate(doc) for doc in docs],
    )


@router.get(
    "/{doc_id}",
    response_model=DocumentResponse,
    summary="查询单个文档详情（可用于轮询处理状态）",
)
async def get_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    根据文档 ID 查询详情。
    主要用途：上传后前端定时轮询此接口，通过 status 字段了解向量化进度。

    轮询建议：每 2 秒查询一次，直到 status = 'completed' 或 'failed'。
    """
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文档 ID={doc_id} 不存在",
        )

    return DocumentResponse.model_validate(doc)


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除文档及其向量数据",
    description="先从 pgvector 删除该文档的所有向量，再从数据库删除文档记录。",
)
async def delete_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    删除文档。执行顺序：
      1. 确认文档存在
      2. 若 status=processing，拒绝删除（避免数据不一致）
      3. 从 pgvector 删除该文档的向量数据（直接 SQL，不受 top_k 限制）
      4. 从 documents 表删除记录
    """
    # ---- 1. 查询文档是否存在 ----
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文档 ID={doc_id} 不存在",
        )

    # ---- 2. 拒绝删除正在处理中的文档 ----
    # 原因：向量化过程中可能正在写入 pgvector，
    # 此时删除向量数据会导致部分数据残留，状态也无法正确更新
    if doc.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档正在处理中（processing），请等待处理完成后再删除",
        )

    kb_id = doc.kb_id
    filename = doc.filename

    # ---- 3. 从 pgvector 删除向量数据 ----
    # 只有已向量化（completed）的文档才有向量数据需要删除
    # pending / failed 状态的文档可能没有向量，删除操作会安全地返回 0 条
    try:
        await document_service.delete_document_vectors(kb_id=kb_id, doc_id=doc_id)
        logger.info(f"doc_id={doc_id} 的向量数据已删除")
    except Exception as e:
        # 向量删除失败不应阻止文档记录的删除（容忍部分失败）
        # 记录错误日志，数据库记录仍然删除
        logger.error(f"删除 doc_id={doc_id} 向量时出错（将继续删除记录）：{e}")

    # ---- 4. 从数据库删除文档记录 ----
    await db.delete(doc)
    # get_db 依赖注入会在函数结束时自动 commit，此处无需手动调用
    logger.info(f"文档已删除：doc_id={doc_id}，filename={filename}，kb_id={kb_id}")

    # 204 No Content 不返回响应体，FastAPI 会自动处理（函数返回 None 即可）
