from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agw.adapters.mcp import MCPHTTPClient, UpstreamError
from agw.api.deps import get_principal, get_store
from agw.audit.service import record
from agw.audit.tracing import record_span
from agw.config import Settings
from agw.core.errors import ApiError, feature_unavailable, forbidden, not_found
from agw.core.runtime import feature_enabled
from agw.core.time import utcnow
from agw.db.models import Agent
from agw.policy.engine import Principal, evaluate_tool_call
from agw.store.base import Store

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _error(rpc_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": error}


def _result(rpc_id: Any, result: dict[str, Any]) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _wants_sse(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "")


def _respond(
    payload: dict, request: Request, settings: Settings
) -> JSONResponse | StreamingResponse:
    if not _wants_sse(request):
        return JSONResponse(payload)
    if not feature_enabled(settings, "mcp_sse"):
        raise ApiError(409, "persistent_runtime_required", "SSE requires the persistent runtime")
    body = f"event: message\ndata: {json.dumps(payload)}\n\n"

    async def stream():
        yield body

    return StreamingResponse(stream(), media_type="text/event-stream")


async def _resolve_agent(store: Store, principal: Principal, slug: str) -> Agent:
    if principal.kind != "agent":
        raise forbidden("forbidden", "MCP endpoint requires an agent credential")
    agent = await store.get_agent_by_slug(principal.workspace_id, slug)
    if agent is None:
        raise not_found("agent")
    if principal.agent_id != agent.id:
        raise forbidden("forbidden", "credential does not belong to this agent")
    return agent


@router.post("/{agent_slug}")
async def mcp_endpoint(
    agent_slug: str,
    request: Request,
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
):
    settings: Settings = request.app.state.settings
    if (
        settings.runtime.value == "request_response"
        and request.headers.get("mcp-session-id")
    ):
        raise ApiError(
            409, "persistent_runtime_required", "MCP sessions require the persistent runtime"
        )
    agent = await _resolve_agent(store, principal, agent_slug)

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ApiError(400, "invalid_request", "body must be JSON") from exc
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "notifications/initialized":
        return JSONResponse({}, status_code=202)

    if method == "initialize":
        instructions = (
            "Stateless runtime: JSON responses only, no sessions, no streaming."
            if settings.runtime.value == "request_response"
            else "Persistent runtime: JSON and SSE responses are available."
        )
        return _respond(
            _result(
                rpc_id,
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "ai-gateway", "version": "0.1.0"},
                    "instructions": instructions,
                },
            ),
            request,
            settings,
        )

    grants = await store.list_active_grants(agent.id)
    services_by_id = {
        service.id: service
        for service in await store.list_services_by_ids(
            [grant.service_id for grant in grants]
        )
    }

    if method == "tools/list":
        tools: list[dict[str, Any]] = []
        for grant in grants:
            if grant.expires_at is not None and grant.expires_at <= utcnow():
                continue
            service = services_by_id.get(grant.service_id)
            if service is None or service.status != "active":
                continue
            for tool in await store.list_tools(service.id):
                if tool.name not in (grant.tools or []):
                    continue
                tools.append(
                    {
                        "name": f"{service.name}__{tool.name}",
                        "description": tool.description or "",
                        "inputSchema": tool.input_schema or {},
                        "annotations": tool.annotations or {},
                    }
                )
        return _respond(_result(rpc_id, {"tools": tools}), request, settings)

    if method == "tools/call":
        call_started = time.perf_counter()
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or "__" not in name:
            return _respond(
                _error(rpc_id, -32602, "tool name must be namespaced as service__tool"),
                request,
                settings,
            )
        service_name, tool_name = name.split("__", 1)
        service = next(
            (s for s in services_by_id.values() if s.name == service_name), None
        )
        if service is None:
            return _respond(_error(rpc_id, -32601, "tool not found"), request, settings)
        tool = await store.get_tool(service.id, tool_name)
        if tool is None:
            return _respond(_error(rpc_id, -32601, "tool not found"), request, settings)
        grant = next((g for g in grants if g.service_id == service.id), None)
        decision = evaluate_tool_call(
            principal,
            agent=agent,
            service=service,
            tool_name=tool.name,
            grant=grant,
            arguments=arguments,
            now=utcnow(),
        )
        await record(
            store,
            workspace_id=agent.workspace_id,
            actor_type="agent",
            actor_id=agent.id,
            action="mcp.tools_call",
            resource_type="service_tool",
            resource_id=str(tool.id),
            decision="allow" if decision.allowed else "deny",
            reason=decision.reason,
            trace_id=request.state.trace_id,
            meta={"service": service.name, "tool": tool.name},
        )
        if not decision.allowed:
            await record_span(
                store,
                workspace_id=agent.workspace_id,
                trace_id=request.state.trace_id,
                name=f"mcp {service.name}.{tool.name}",
                parent_span_id="root",
                kind="client",
                status="error",
                duration_ms=int((time.perf_counter() - call_started) * 1000),
                actor_type="agent",
                actor_id=agent.id,
                attributes={"decision": "deny", "reason": decision.reason},
            )
            await store.commit()
            return _respond(
                _error(
                    rpc_id,
                    -32003,
                    "tool call denied",
                    {"code": decision.code, "reason": decision.reason},
                ),
                request,
                settings,
            )
        if service.auth_type != "none":
            await store.commit()
            return _respond(
                _error(
                    rpc_id,
                    -32001,
                    "connection required",
                    {
                        "service_id": str(service.id),
                        "code": "connection_required",
                    },
                ),
                request,
                settings,
            )
        if service.kind != "mcp_http" or not service.endpoint:
            await store.commit()
            return _respond(
                _error(
                    rpc_id,
                    -32004,
                    "this service kind is not callable yet",
                    {"code": "feature_unavailable"},
                ),
                request,
                settings,
            )
        try:
            result = await MCPHTTPClient(
                service.endpoint, timeout=settings.tool_timeout_seconds
            ).call_tool(tool.name, arguments)
        except (UpstreamError, httpx.HTTPError) as exc:
            await record_span(
                store,
                workspace_id=agent.workspace_id,
                trace_id=request.state.trace_id,
                name=f"mcp {service.name}.{tool.name}",
                parent_span_id="root",
                kind="client",
                status="error",
                duration_ms=int((time.perf_counter() - call_started) * 1000),
                actor_type="agent",
                actor_id=agent.id,
                attributes={"decision": "allow", "error": str(exc)},
            )
            await store.commit()
            return _respond(
                _error(
                    rpc_id,
                    -32004,
                    "upstream call failed",
                    {"code": "upstream_error", "detail": str(exc)},
                ),
                request,
                settings,
            )
        await record_span(
            store,
            workspace_id=agent.workspace_id,
            trace_id=request.state.trace_id,
            name=f"mcp {service.name}.{tool.name}",
            parent_span_id="root",
            kind="client",
            status="ok",
            duration_ms=int((time.perf_counter() - call_started) * 1000),
            actor_type="agent",
            actor_id=agent.id,
            attributes={"decision": "allow"},
        )
        await store.commit()
        payload = {
            "content": result.get("content", []),
            "isError": bool(result.get("isError", False)),
        }
        if "structuredContent" in result:
            payload["structuredContent"] = result["structuredContent"]
        return _respond(_result(rpc_id, payload), request, settings)

    return _respond(_error(rpc_id, -32601, f"unknown method: {method}"), request, settings)
