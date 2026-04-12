from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Local MCP Bridge", version="0.2.0")


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


_CURRENCY_ALIAS = {
    "USD": "USD",
    "CNY": "CNY",
    "RMB": "CNY",
    "HKD": "HKD",
    "JPY": "JPY",
    "EUR": "EUR",
    "GBP": "GBP",
    "AUD": "AUD",
    "CAD": "CAD",
    "CHF": "CHF",
    "SGD": "SGD",
    "NZD": "NZD",
    "美元": "USD",
    "人民币": "CNY",
    "港币": "HKD",
    "日元": "JPY",
    "欧元": "EUR",
    "英镑": "GBP",
    "澳元": "AUD",
    "加元": "CAD",
    "瑞郎": "CHF",
    "新加坡元": "SGD",
    "纽元": "NZD",
}


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
        },
        {
            "name": "fx_rate",
            "description": "Get foreign exchange rate by currency pair.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "default": "USD"},
                    "quote": {"type": "string", "default": "CNY"},
                    "query": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": [],
            },
        },
    ]


@app.post("/tools/{tool_name}/call")
async def call_tool(tool_name: str, req: ToolCallRequest) -> dict[str, Any]:
    if tool_name == "web_search":
        return await _call_web_search(req.arguments)
    if tool_name == "fx_rate":
        return await _call_fx_rate(req.arguments)
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")


def _extract_currency_pair_from_query(query: str) -> tuple[str, str]:
    text = query.upper()
    code_pairs = re.findall(r"\b([A-Z]{3})\s*[/\s]\s*([A-Z]{3})\b", text)
    for base, quote in code_pairs:
        if base in _CURRENCY_ALIAS and quote in _CURRENCY_ALIAS:
            return _CURRENCY_ALIAS[base], _CURRENCY_ALIAS[quote]

    found: list[str] = []
    for alias, code in _CURRENCY_ALIAS.items():
        if alias in query:
            found.append(code)
    dedup: list[str] = []
    for code in found:
        if code not in dedup:
            dedup.append(code)
    if len(dedup) >= 2:
        return dedup[0], dedup[1]

    return "USD", "CNY"


def _normalize_currency(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    raw = value.strip()
    if not raw:
        return fallback
    key = raw.upper()
    if key in _CURRENCY_ALIAS:
        return _CURRENCY_ALIAS[key]
    if raw in _CURRENCY_ALIAS:
        return _CURRENCY_ALIAS[raw]
    return fallback


async def _call_web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    top_k = int(arguments.get("top_k", 5))
    top_k = max(1, min(top_k, 10))
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    params = {"q": query, "format": "json", "no_redirect": 1, "no_html": 1}
    hits: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
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


async def _call_fx_rate(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    guessed_base, guessed_quote = _extract_currency_pair_from_query(query)
    base = _normalize_currency(arguments.get("base"), guessed_base)
    quote = _normalize_currency(arguments.get("quote"), guessed_quote)
    date = str(arguments.get("date", "")).strip()

    endpoint = "latest" if not date else date
    url = f"https://api.frankfurter.app/{endpoint}"
    params = {"from": base, "to": quote}

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    rates = data.get("rates", {})
    if not isinstance(rates, dict) or quote not in rates:
        return {"hits": []}

    rate = rates[quote]
    quoted_date = data.get("date") or date or "latest"
    source_url = str(resp.url)
    snippet = f"1 {base} = {rate} {quote} (date: {quoted_date})"

    return {
        "hits": [
            {
                "title": f"{base}/{quote} FX",
                "url": source_url,
                "snippet": snippet,
                "score": 1.0,
                "base": base,
                "quote": quote,
                "rate": rate,
                "date": quoted_date,
                "source_type": "api",
            }
        ]
    }
