from __future__ import annotations

import re
from typing import Any

import httpx

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_SPEC_SUFFIXES = (".json", ".yaml", ".yml")


class OpenAPIDiscoveryError(Exception):
    """Raised when no usable OpenAPI document can be fetched from an endpoint."""


def _resolve(document: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return {}
    node: Any = document
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict):
            return {}
        node = node.get(part, {})
    return node


def _deref(document: dict[str, Any], value: Any, depth: int = 0) -> Any:
    if depth > 10:
        return value
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            return _deref(document, _resolve(document, ref), depth + 1)
        return {key: _deref(document, item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_deref(document, item, depth + 1) for item in value]
    return value


def _tool_name(method: str, path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    return f"{method}_{slug}" if slug else method


def _input_schema(
    document: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    parameters = list(path_item.get("parameters") or []) + list(
        operation.get("parameters") or []
    )
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        parameter = _deref(document, parameter)
        if not isinstance(parameter, dict) or "$ref" in parameter:
            continue
        name = parameter.get("name")
        if not isinstance(name, str):
            continue
        schema = _deref(document, parameter.get("schema") or {"type": "string"})
        if not isinstance(schema, dict):
            schema = {"type": "string"}
        description = parameter.get("description")
        if description:
            schema = {**schema, "description": description}
        properties[name] = schema
        if parameter.get("required"):
            required.append(name)

    request_body = _deref(document, operation.get("requestBody") or {})
    if isinstance(request_body, dict):
        content = request_body.get("content") or {}
        if isinstance(content, dict) and content:
            media = content.get("application/json") or next(iter(content.values()))
            body_schema = _deref(document, (media or {}).get("schema") or {})
            if isinstance(body_schema, dict) and body_schema.get("type") == "object":
                for key, value in (body_schema.get("properties") or {}).items():
                    properties[key] = value
                required.extend(
                    item for item in body_schema.get("required") or [] if item not in required
                )
            elif body_schema:
                properties["body"] = body_schema
                if request_body.get("required"):
                    required.append("body")

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = sorted(set(required))
    return schema


def openapi_tools(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert OpenAPI operations into tool definitions usable by the gateway."""
    tools: list[dict[str, Any]] = []
    used: set[str] = set()
    paths = document.get("paths") or {}
    if not isinstance(paths, dict):
        return tools

    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            name = operation.get("operationId")
            if not isinstance(name, str) or not name:
                name = _tool_name(method, path)
            base = name
            suffix = 2
            while name in used:
                name = f"{base}_{suffix}"
                suffix += 1
            used.add(name)
            tools.append(
                {
                    "name": name,
                    "description": operation.get("summary")
                    or operation.get("description"),
                    "inputSchema": _input_schema(document, path_item, operation),
                    "annotations": {
                        "http_method": method.upper(),
                        "path": path,
                        "source": "openapi",
                    },
                }
            )
    return tools


def _candidates(endpoint: str) -> list[str]:
    base = endpoint.rstrip("/")
    if base.lower().endswith(_SPEC_SUFFIXES):
        return [base]
    return [f"{base}/openapi.json", f"{base}/swagger.json", base]


async def fetch_openapi(endpoint: str, *, timeout: float = 10.0) -> dict[str, Any]:
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in _candidates(endpoint):
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                errors.append(f"{url}: {exc}")
                continue
            if response.status_code >= 400:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            try:
                document = response.json()
            except ValueError:
                errors.append(f"{url}: response is not JSON")
                continue
            if isinstance(document, dict) and (
                "openapi" in document or "swagger" in document
            ):
                return document
            errors.append(f"{url}: not an OpenAPI document")
    raise OpenAPIDiscoveryError("; ".join(errors) or "no OpenAPI document found")
