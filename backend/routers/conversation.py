# ==================================================
# 对话历史路由模块
# 提供对话列表查询、详情查询、删除等接口
# 前缀：/api/v1/conversations（在 main.py 中注册）
# ==================================================

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.conversation import Conversation
from models.message import Message

router = APIRouter()


# --------------------------------------------------
# Pydantic Schema
# --------------------------------------------------

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    token_count: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: int
    kb_id: int
    title: str
    created_at: datetime
    last_active_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: int
    kb_id: int
    title: str
    created_at: datetime
    last_active_at: datetime
    messages: list[MessageResponse] = Field(default=[], description="消息列表，按时间升序")


class ConversationListResponse(BaseModel):
    total: int
    items: list[ConversationResponse]


class ConversationTitleUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="新的对话标题")


# --------------------------------------------------
# 接口实现
# --------------------------------------------------

@router.get(
    "/",
    response_model=ConversationListResponse,
    summary="获取对话列表",
)
async def list_conversations(
    kb_id: int,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    # 总数
    count_result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.kb_id == kb_id)
    )
    total = count_result.scalar() or 0

    # 列表（按最后活跃时间降序）
    result = await db.execute(
        select(Conversation)
        .where(Conversation.kb_id == kb_id)
        .order_by(Conversation.last_active_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(result.scalars().all())

    return ConversationListResponse(total=total, items=items)


@router.get(
    "/{conv_id}",
    response_model=ConversationDetailResponse,
    summary="获取对话详情（含完整消息历史）",
)
async def get_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
):
    # 查对话
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")

    # 查消息列表（按创建时间升序）
    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    messages = list(msg_result.scalars().all())

    return ConversationDetailResponse(
        id=conv.id,
        kb_id=conv.kb_id,
        title=conv.title,
        created_at=conv.created_at,
        last_active_at=conv.last_active_at,
        messages=messages,
    )


@router.put(
    "/{conv_id}",
    response_model=ConversationResponse,
    summary="更新对话标题",
)
async def update_conversation_title(
    conv_id: int,
    data: ConversationTitleUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")

    conv.title = data.title
    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete(
    "/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除对话",
)
async def delete_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail=f"对话 {conv_id} 不存在")

    # 先删消息，再删对话
    await db.execute(sa_delete(Message).where(Message.conversation_id == conv_id))
    await db.delete(conv)
    await db.commit()
