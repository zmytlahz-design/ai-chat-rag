from __future__ import annotations

import logging
from typing import AsyncIterator
from urllib.parse import urlparse

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services.answer_guard import build_no_evidence_message, build_tool_failure_message
from services.local_tools import local_tool_service
from services.mcp_client_manager import mcp_client_manager

logger = logging.getLogger(__name__)


GROUNDED_QA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是一个严格基于证据回答的助手。
规则：
1. 只能依据给定证据回答，禁止编造。
2. 如果证据不足，直接回复“当前证据不足，无法确认”。
3. 结论后必须附来源标注，格式：[来源: 文件名#chunk_index]。
4. 回答简洁、结构清晰，优先用中文。""",
        ),
        ("human", "历史对话：\n{chat_history}\n\n问题：\n{question}\n\n证据：\n{evidence}"),
    ]
)


class AgentService:
    """工具增强聊天服务：先调工具，再基于证据生成回答。"""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_NAME,
            openai_api_key=settings.LLM_API_KEY,
            openai_api_base=settings.LLM_BASE_URL,
            temperature=0.2,
            max_tokens=settings.LLM_MAX_TOKENS,
            streaming=True,
        )

    @staticmethod
    def _format_history(chat_history: list[dict]) -> str:
        if not chat_history:
            return "（暂无历史对话）"
        lines: list[str] = []
        for msg in chat_history:
            role = "用户" if msg.get("role") == "user" else "助手"
            lines.append(f"{role}：{msg.get('content', '')}")
        return "\n".join(lines)

    @staticmethod
    def _pick_tool(question: str) -> str:
        q = question.lower()
        if any(k in q for k in ["文档状态", "处理状态", "失败文档", "上传状态", "哪些文档"]):
            return "get_doc_status"
        if any(k in q for k in ["知识库概览", "知识库情况", "文档总数", "多少文档", "完成了多少"]):
            return "get_kb_summary"
        if any(k in q for k in ["对话数", "会话数", "消息数", "活跃", "近7天", "近 7 天"]):
            return "get_conversation_stats"
        return "kb_semantic_search"

    @staticmethod
    def _is_web_intent(question: str) -> bool:
        q = question.lower()
        keywords = [
            "最新", "今天", "最近", "新闻", "股价", "汇率", "天气",
            "实时", "price", "today", "latest", "news",
        ]
        return any(k in q for k in keywords)

    @staticmethod
    def _is_fx_intent(question: str) -> bool:
        q = question.lower()
        keywords = [
            "汇率",
            "美元兑",
            "人民币兑",
            "usd",
            "cny",
            "rmb",
            "exchange rate",
            "fx",
        ]
        return any(k in q for k in keywords)

    async def _run_mcp_fx_rate(self, question: str) -> dict:
        tool_name = settings.MCP_FX_TOOL_NAME
        raw = await mcp_client_manager.call_tool(
            name=tool_name,
            arguments={"query": question},
        )

        candidates = []
        if isinstance(raw.get("hits"), list):
            candidates = raw.get("hits", [])
        elif isinstance(raw.get("items"), list):
            candidates = raw.get("items", [])
        elif isinstance(raw.get("results"), list):
            candidates = raw.get("results", [])

        hits = []
        for item in candidates[: settings.MCP_MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "汇率结果")
            url = str(item.get("url") or item.get("link") or "")
            snippet = str(item.get("snippet") or item.get("content") or item.get("summary") or "")
            hits.append(
                {
                    "source_type": "api",
                    "title": title,
                    "url": url,
                    "content": snippet,
                    "score": float(item.get("score", 1.0)),
                }
            )

        return {
            "query": question,
            "hits": hits,
            "provider": "mcp",
            "tool": tool_name,
        }

    async def _run_mcp_web_search(self, question: str) -> dict:
        tool_name = settings.MCP_WEB_TOOL_NAME
        raw = await mcp_client_manager.call_tool(
            name=tool_name,
            arguments={
                "query": question,
                "top_k": settings.MCP_MAX_RESULTS,
            },
        )

        candidates = []
        if isinstance(raw.get("hits"), list):
            candidates = raw.get("hits", [])
        elif isinstance(raw.get("items"), list):
            candidates = raw.get("items", [])
        elif isinstance(raw.get("results"), list):
            candidates = raw.get("results", [])

        hits = []
        for item in candidates[: settings.MCP_MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "网页结果")
            url = str(item.get("url") or item.get("link") or "")
            snippet = str(item.get("snippet") or item.get("content") or item.get("summary") or "")
            hits.append(
                {
                    "source_type": "web",
                    "title": title,
                    "url": url,
                    "content": snippet,
                    "score": float(item.get("score", 1.0)),
                }
            )

        return {
            "query": question,
            "hits": hits,
            "provider": "mcp",
            "tool": tool_name,
        }

    async def _run_tool(
        self,
        db: AsyncSession,
        kb_id: int,
        question: str,
    ) -> tuple[str, dict]:
        tool_name = self._pick_tool(question)
        if tool_name == "get_doc_status":
            result = await local_tool_service.get_doc_status(db=db, kb_id=kb_id, limit=50)
        elif tool_name == "get_kb_summary":
            result = await local_tool_service.get_kb_summary(db=db, kb_id=kb_id)
        elif tool_name == "get_conversation_stats":
            result = await local_tool_service.get_conversation_stats(db=db, kb_id=kb_id, days=7)
        else:
            # 汇率类问题优先走 MCP 专用工具，避免被本地文档误命中
            if settings.ENABLE_MCP and self._is_fx_intent(question):
                try:
                    fx_result = await self._run_mcp_fx_rate(question)
                    if fx_result.get("hits"):
                        return "mcp_fx_rate", fx_result
                except Exception as fx_error:
                    logger.warning("fx_rate 调用失败，回退到其他策略: %s", fx_error)

            result = await local_tool_service.kb_semantic_search(
                kb_id=kb_id,
                query=question,
                top_k=5,
                min_score=settings.RAG_MIN_SCORE,
            )
            # 当本地知识库证据不足且用户问题偏实时信息时，尝试走 MCP 联网检索
            if (
                settings.ENABLE_MCP
                and self._is_web_intent(question)
                and not result.get("hits")
            ):
                mcp_result = await self._run_mcp_web_search(question)
                return "mcp_web_search", mcp_result
        return tool_name, result

    @staticmethod
    def _build_sources_from_hits(hits: list[dict]) -> list[dict]:
        sources: list[dict] = []
        for hit in hits:
            if hit.get("source_type") in {"web", "api"}:
                title = hit.get("title") or "网页结果"
                url = hit.get("url") or ""
                domain = ""
                if url:
                    try:
                        domain = urlparse(url).netloc
                    except Exception:
                        domain = ""
                filename = f"{title} ({domain})" if domain else str(title)
                snippet = hit.get("content", "")
                content = f"{snippet}\n链接: {url}" if url else str(snippet)
                sources.append(
                    {
                        "doc_id": None,
                        "filename": filename,
                        "chunk_index": 0,
                        "content": content,
                    }
                )
            else:
                sources.append(
                    {
                        "doc_id": hit.get("doc_id"),
                        "filename": hit.get("filename", "未知文件"),
                        "chunk_index": hit.get("chunk_index", 0),
                        "content": hit.get("content", ""),
                    }
                )
        return sources

    @staticmethod
    def _render_status_answer(tool_name: str, result: dict) -> str:
        if tool_name == "get_kb_summary":
            return (
                f"知识库「{result.get('kb_name', '-') }」当前情况：\n"
                f"- 文档总数：{result.get('document_total', 0)}\n"
                f"- 已完成：{result.get('document_completed', 0)}\n"
                f"- 处理中：{result.get('document_processing', 0)}\n"
                f"- 失败：{result.get('document_failed', 0)}"
            )
        if tool_name == "get_doc_status":
            items = result.get("items", [])
            if not items:
                return "当前知识库暂无文档记录。"
            lines = ["文档状态如下："]
            for item in items[:10]:
                lines.append(
                    f"- {item.get('filename')}：{item.get('status')}（chunk={item.get('chunk_count', 0)}）"
                )
            return "\n".join(lines)
        if tool_name == "get_conversation_stats":
            return (
                f"近 {result.get('days', 7)} 天统计：\n"
                f"- 对话数：{result.get('conversation_count', 0)}\n"
                f"- 消息数：{result.get('message_count', 0)}\n"
                f"- 最近活跃：{result.get('last_active_at') or '暂无'}"
            )
        return "工具执行完成。"

    @staticmethod
    def _is_structured_tool(tool_name: str) -> bool:
        return tool_name in {
            "get_kb_summary",
            "get_doc_status",
            "get_conversation_stats",
        }

    @staticmethod
    def _build_evidence_text(hits: list[dict]) -> str:
        parts: list[str] = []
        for hit in hits:
            if hit.get("source_type") in {"web", "api"}:
                title = hit.get("title", "网页结果")
                url = hit.get("url", "")
                parts.append(
                    f"[来源: {title} | url={url} | score={hit.get('score', 1.0)}]\n"
                    f"{hit.get('content', '')}"
                )
            else:
                parts.append(
                    f"[来源: {hit.get('filename', '未知文件')}#{hit.get('chunk_index', 0)} | "
                    f"score={hit.get('score', 0)}]\n{hit.get('content', '')}"
                )
        return "\n\n".join(parts)

    async def generate_answer(
        self,
        db: AsyncSession,
        question: str,
        kb_id: int,
        chat_history: list[dict],
    ) -> tuple[str, list[dict]]:
        try:
            tool_name, tool_result = await self._run_tool(db=db, kb_id=kb_id, question=question)
        except Exception as e:
            logger.error("工具调用失败: %s", e, exc_info=True)
            return build_tool_failure_message(), []

        if self._is_structured_tool(tool_name):
            return self._render_status_answer(tool_name, tool_result), []

        hits = tool_result.get("hits", [])
        if settings.STRICT_GROUNDING and not hits:
            return build_no_evidence_message(), []

        evidence_text = self._build_evidence_text(hits)
        history_text = self._format_history(chat_history)
        messages = GROUNDED_QA_PROMPT.format_messages(
            chat_history=history_text,
            question=question,
            evidence=evidence_text,
        )
        response = await self.llm.ainvoke(messages)
        return response.content, self._build_sources_from_hits(hits)

    async def generate_answer_stream(
        self,
        db: AsyncSession,
        question: str,
        kb_id: int,
        chat_history: list[dict],
    ) -> AsyncIterator[dict]:
        try:
            tool_name, tool_result = await self._run_tool(db=db, kb_id=kb_id, question=question)
            yield {"type": "tool_start", "tool": tool_name}
            yield {
                "type": "tool_result",
                "tool": tool_name,
                "ok": True,
                "summary": local_tool_service.summarize_tool_result(tool_name, tool_result),
            }
        except Exception as e:
            logger.error("工具调用失败: %s", e, exc_info=True)
            yield {"type": "tool_result", "tool": "unknown", "ok": False, "summary": str(e)}
            yield {"type": "token", "content": build_tool_failure_message()}
            yield {"type": "sources", "sources": []}
            return

        if self._is_structured_tool(tool_name):
            yield {"type": "token", "content": self._render_status_answer(tool_name, tool_result)}
            yield {"type": "sources", "sources": []}
            return

        hits = tool_result.get("hits", [])
        if settings.STRICT_GROUNDING and not hits:
            yield {"type": "token", "content": build_no_evidence_message()}
            yield {"type": "sources", "sources": []}
            return

        evidence_text = self._build_evidence_text(hits)
        history_text = self._format_history(chat_history)
        messages = GROUNDED_QA_PROMPT.format_messages(
            chat_history=history_text,
            question=question,
            evidence=evidence_text,
        )

        async for chunk in self.llm.astream(messages):
            token_text = chunk.content
            if token_text:
                yield {"type": "token", "content": token_text}

        yield {"type": "sources", "sources": self._build_sources_from_hits(hits)}


agent_service = AgentService()
