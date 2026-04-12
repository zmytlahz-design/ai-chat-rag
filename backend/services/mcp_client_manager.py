from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    轻量 MCP bridge 客户端。

    约定支持两种常见网关形态（自动尝试）：
    1) REST:
       - GET  {base}/tools
       - POST {base}/tools/{name}/call   body={"arguments": {...}}
    2) JSON-RPC:
       - POST {base}/rpc
         {"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":...,"arguments":...}}
    """

    def __init__(self) -> None:
        self.base_url = settings.MCP_BRIDGE_URL.strip().rstrip("/")
        self.timeout = settings.MCP_TIMEOUT_SEC
        self.api_key = settings.MCP_API_KEY.strip()

    @property
    def enabled(self) -> bool:
        return settings.ENABLE_MCP and bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers()) as client:
            try:
                resp = await client.get(f"{self.base_url}/tools")
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and isinstance(data.get("tools"), list):
                    return data["tools"]
            except Exception as e:
                logger.warning("MCP list_tools 失败: %s", e)
        return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("MCP 未启用或 MCP_BRIDGE_URL 未配置")

        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers()) as client:
            # 1) 先尝试 REST 风格
            try:
                rest_resp = await client.post(
                    f"{self.base_url}/tools/{name}/call",
                    json={"arguments": arguments},
                )
                rest_resp.raise_for_status()
                rest_data = rest_resp.json()
                return self._normalize_result(rest_data)
            except Exception as rest_err:
                logger.debug("MCP REST 调用失败，尝试 JSON-RPC: %s", rest_err)

            # 2) 退化尝试 JSON-RPC 风格
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": "codex-agent-1",
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments,
                },
            }
            rpc_resp = await client.post(f"{self.base_url}/rpc", json=rpc_payload)
            rpc_resp.raise_for_status()
            rpc_data = rpc_resp.json()
            if isinstance(rpc_data, dict) and rpc_data.get("error"):
                raise RuntimeError(f"MCP RPC error: {rpc_data['error']}")
            result = rpc_data.get("result") if isinstance(rpc_data, dict) else rpc_data
            return self._normalize_result(result)

    @staticmethod
    def _normalize_result(data: Any) -> dict[str, Any]:
        # 兼容常见网关返回结构
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], dict):
                return data["result"]
            return data
        if isinstance(data, list):
            return {"items": data}
        return {"raw": data}


mcp_client_manager = MCPClientManager()

