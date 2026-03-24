# ==================================================
# 知识库路由模块
# 提供知识库的增删改查（CRUD）接口
# 前缀：/api/v1/knowledge-bases（在 main.py 中注册）
# ==================================================

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.knowledge_base import KnowledgeBase
from models.document import Document
from models.conversation import Conversation
from models.message import Message

router = APIRouter()


# --------------------------------------------------
# Pydantic 数据模型（请求/响应 Schema）
# --------------------------------------------------

class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="知识库名称")
    description: Optional[str] = Field(None, max_length=2000, description="知识库描述")


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class KnowledgeBaseResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeBaseListResponse(BaseModel):
    total: int = Field(description="总数量")
    items: list[KnowledgeBaseResponse] = Field(description="知识库列表")


# --------------------------------------------------
# CRUD 接口
# --------------------------------------------------

@router.post(
    "/",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建知识库",
)
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
):
    kb = KnowledgeBase(name=data.name, description=data.description)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get(
    "/",
    response_model=KnowledgeBaseListResponse,
    summary="获取知识库列表",
)
async def list_knowledge_bases(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    # 查询总数
    count_result = await db.execute(select(func.count(KnowledgeBase.id)))
    total = count_result.scalar() or 0

    # 分页查询列表，按创建时间降序
    result = await db.execute(
        select(KnowledgeBase)
        .order_by(KnowledgeBase.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(result.scalars().all())

    return KnowledgeBaseListResponse(total=total, items=items)


@router.get(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="获取单个知识库详情",
)
async def get_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    return kb


@router.put(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="更新知识库信息",
)
async def update_knowledge_base(
    kb_id: int,
    data: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")

    # 只更新传入的非 None 字段
    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description

    await db.commit()
    await db.refresh(kb)
    return kb


@router.delete(
    "/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除知识库",
)
async def delete_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")

    # 级联删除：先删消息 → 对话 → 文档 → 知识库
    # 查出该 KB 下所有对话 ID
    conv_result = await db.execute(
        select(Conversation.id).where(Conversation.kb_id == kb_id)
    )
    conv_ids = [row[0] for row in conv_result.all()]

    if conv_ids:
        await db.execute(sa_delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(sa_delete(Conversation).where(Conversation.kb_id == kb_id))

    await db.execute(sa_delete(Document).where(Document.kb_id == kb_id))
    await db.delete(kb)
    await db.commit()

