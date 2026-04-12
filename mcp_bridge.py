from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Local MCP Bridge", version="0.1.0")


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tools")
async def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "web_search",
            "description": "Search web snippets by query.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        }
    ]


@app.post("/tools/{tool_name}/call")
async def call_tool(tool_name: str, req: ToolCallRequest) -> dict[str, Any]:
    if tool_name != "web_search":
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    query = str(req.arguments.get("query", "")).strip()
    top_k = int(req.arguments.get("top_k", 5))
    top_k = max(1, min(top_k, 10))
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    params = {
        "q": query,
        "format": "json",
        "no_redirect": 1,
        "no_html": 1,
    }

    hits: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.get("https://api.duckduckgo.com/", params=params)
        resp.raise_for_status()
        data = resp.json()

    abstract_text = data.get("AbstractText")
    if isinstance(abstract_text, str) and abstract_text.strip():
        hits.append(
            {
                "title": data.get("Heading") or "DuckDuckGo",
                "url": data.get("AbstractURL") or "",
                "snippet": abstract_text,
                "score": 1.0,
            }
        )

    related = data.get("RelatedTopics", [])
    if isinstance(related, list):
        for item in related:
            if len(hits) >= top_k:
                break
            if not isinstance(item, dict):
                continue
            text = item.get("Text")
            if isinstance(text, str) and text.strip():
                hits.append(
                    {
                        "title": text.split(" - ")[0][:80] or "Result",
                        "url": item.get("FirstURL") or "",
                        "snippet": text,
                        "score": 0.9,
                    }
                )

    return {"hits": hits[:top_k]}

