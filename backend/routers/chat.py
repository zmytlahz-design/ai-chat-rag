# ==================================================
# 对话路由模块（完整实现）
# 前缀：/api/v1/chat（在 main.py 中注册）
#
# 接口列表：
#   POST /stream   流式对话（SSE，前端实时显示打字效果）
#   POST /normal   普通对话（等待完整回复后一次性返回）
#
# 流式 vs 普通的选择建议：
#   - 流式：用户体验好，有打字机效果，长回复首字延迟低
#   - 普通：实现简单，适合批量调用或不支持流式的客户端
# ==================================================

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
# StreamingResponse：FastAPI 原生支持的流式响应类
# 接受一个异步生成器，HTTP 响应会随生成器 yield 逐步发送到客户端
# media_type="text/event-stream" 是 SSE（Server-Sent Events）标准的 MIME 类型

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.chat_service import chat_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================================================
# Pydantic Schema
# ==================================================

class ChatStreamRequest(BaseModel):
    """流式对话请求体"""
    kb_id: int = Field(..., description="知识库 ID，AI 将基于此知识库的文档回答")
    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="用户的问题",
    )
    conversation_id: Optional[int] = Field(
        None,
        description="对话 ID；传 null 或不传则自动创建新对话",
    )


class ChatNormalRequest(BaseModel):
    """普通对话请求体（与流式相同，便于独立扩展）"""
    kb_id: int = Field(..., description="知识库 ID")
    question: str = Field(..., min_length=1, max_length=5000, description="用户的问题")
    conversation_id: Optional[int] = Field(None, description="对话 ID，空则创建新对话")


class SourceDocumentResponse(BaseModel):
    """AI 回答时引用的文档片段"""
    doc_id: Optional[int] = Field(None, description="来源文档 ID（documents 表主键）")
    filename: str = Field(description="来源文件名")
    chunk_index: int = Field(description="该片段在文档中的序号")
    content: str = Field(description="具体引用的文本片段（前 300 字）")


class ChatNormalResponse(BaseModel):
    """普通对话响应体"""
    conversation_id: int = Field(description="对话 ID（新建或已有）")
    message_id: Optional[int] = Field(None, description="AI 回复消息的数据库 ID")
    content: str = Field(description="AI 回复的完整内容")
    sources: list[SourceDocumentResponse] = Field(
        default=[],
        description="引用的文档片段列表",
    )
    token_count: Optional[int] = Field(None, description="本次消耗的 token 数（预留）")


# ==================================================
# 接口实现
# ==================================================

@router.post(
    "/stream",
    summary="流式对话（SSE）",
    description="""
基于 RAG 的流式对话接口，使用 **Server-Sent Events** 格式实时推送 AI 回复。

**请求格式：** `application/json`

**响应格式：** `text/event-stream`，每行一个事件：

```
data: {"type": "start",  "conversation_id": 1}
data: {"type": "token",  "content": "根"}
data: {"type": "token",  "content": "据"}
...（每个 token 一条）
data: {"type": "done",   "conversation_id": 1, "message_id": 5, "sources": [...]}
```

**错误事件（RAG 失败时）：**
```
data: {"type": "error", "message": "生成回答时发生错误：..."}
```

**前端接收示例（JavaScript）：**
```javascript
const response = await fetch('/api/v1/chat/stream', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({ kb_id: 1, question: '你好' })
});
const reader = response.body.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const lines = decoder.decode(value).split('\\n\\n');
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6));
      if (event.type === 'token') console.log(event.content);
    }
  }
}
```
    """,
    response_class=StreamingResponse,
)
async def chat_stream(
    request: ChatStreamRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    流式对话接口。

    内部流程：
      1. chat_service.chat_stream() 返回异步生成器（产出 SSE 字符串）
      2. StreamingResponse 包装该生成器，边生成边发送
      3. 前端通过 fetch() + ReadableStream 或 EventSource 接收

    HTTP 响应头说明：
      Cache-Control: no-cache        → 禁止代理/浏览器缓存 SSE 流
      Connection: keep-alive         → 保持 TCP 连接，持续推送数据
      X-Accel-Buffering: no          → 关闭 Nginx 的响应缓冲（否则 Nginx 会攒够一批再发）
      Access-Control-Allow-Origin: * → 允许跨域（实际由 CORS 中间件统一处理）
    """
    # 校验知识库 ID 基本合法性（业务校验在 chat_service 内部做）
    if request.kb_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="kb_id 必须为正整数",
        )

    async def generate():
        """
        异步生成器，包装 chat_service.chat_stream()。
        这一层薄包装的作用：在 chat_service 之上统一处理异常，
        确保即使内部出错也能发送一条 error 事件，而不是静默断流。
        """
        try:
            async for chunk in chat_service.chat_stream(
                db=db,
                kb_id=request.kb_id,
                user_message=request.question,
                conversation_id=request.conversation_id,
            ):
                yield chunk
        except ValueError as e:
            # 业务错误（如知识库不存在）：发送错误事件
            import json
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 未预期错误：记录日志，发送通用错误事件
            logger.error(f"流式对话发生未知错误：{e}", exc_info=True)
            import json
            yield f"data: {json.dumps({'type': 'error', 'message': '服务器内部错误，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",  # SSE 标准 MIME 类型
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # 关闭 Nginx 缓冲，让 token 实时推送
        },
    )


@router.post(
    "/normal",
    response_model=ChatNormalResponse,
    summary="普通对话（非流式）",
    description="""
基于 RAG 的普通对话接口，等待 AI 生成完毕后一次性返回完整回复。

**适用场景：**
- 批量处理（不需要实时显示）
- 客户端不支持 SSE 流式接收
- 测试和调试

**内部流程与流式接口完全相同（RAG 三步链路），只是最后统一返回。**
    """,
)
async def chat_normal(
    request: ChatNormalRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatNormalResponse:
    """
    普通对话接口。

    直接调用 chat_service.chat()，等待完整结果后构造响应对象返回。
    相比流式接口，代码更简单，但用户需要等待整个回复生成完毕。
    """
    if request.kb_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="kb_id 必须为正整数",
        )

    try:
        result = await chat_service.chat(
            db=db,
            kb_id=request.kb_id,
            user_message=request.question,
            conversation_id=request.conversation_id,
        )
    except ValueError as e:
        # 业务逻辑错误（对话 ID 不存在、知识库不存在等）
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"普通对话发生错误：{e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RAG 生成回答时发生内部错误，请稍后重试",
        )

    # 将 sources 字典列表转换为 Pydantic 响应模型
    sources = [
        SourceDocumentResponse(
            doc_id=s.get("doc_id"),
            filename=s.get("filename", "未知文件"),
            chunk_index=s.get("chunk_index", 0),
            content=s.get("content", ""),
        )
        for s in result.get("sources", [])
    ]

    return ChatNormalResponse(
        conversation_id=result["conversation_id"],
        message_id=result.get("message_id"),
        content=result["content"],
        sources=sources,
        token_count=result.get("token_count"),
    )
