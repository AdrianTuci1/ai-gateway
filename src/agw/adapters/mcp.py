from __future__ import annotations

import json
from typing import Any

import httpx


class UpstreamError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.retryable = retryable
        super().__init__(message)


class MCPHTTPClient:
    """Minimal MCP streamable-HTTP client for discovery and tool calls.

    Supports JSON responses and single-event SSE responses. Session headers are
    honoured when the upstream returns them.
    """

    def __init__(self, endpoint: str, *, timeout: float = 30.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.session_id: str | None = None
        self._initialized = False
        self._next_id = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise UpstreamError("SSE response without a data event")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise UpstreamError("upstream returned invalid JSON") from exc

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ai-gateway", "version": "0.1.0"},
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.endpoint, json=payload, headers=self._headers())
        if response.status_code >= 400:
            raise UpstreamError(f"initialize failed with HTTP {response.status_code}")
        self.session_id = response.headers.get("mcp-session-id") or self.session_id
        body = self._decode(response)
        if "error" in body:
            raise UpstreamError(body["error"].get("message", "initialize failed"))
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(self.endpoint, json=notification, headers=self._headers())
        except httpx.HTTPError:
            pass
        self._initialized = True

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.initialize()
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.endpoint, json=payload, headers=self._headers())
        if response.status_code == 401 or response.status_code == 403:
            raise UpstreamError("upstream rejected the credential")
        if response.status_code >= 400:
            raise UpstreamError(
                f"upstream returned HTTP {response.status_code}", retryable=response.status_code >= 500
            )
        body = self._decode(response)
        if "error" in body:
            error = body["error"]
            raise UpstreamError(error.get("message", "upstream error"))
        return body.get("result", {})

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.rpc("tools/list")
        return list(result.get("tools", []))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("tools/call", {"name": name, "arguments": arguments})
