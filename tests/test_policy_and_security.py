from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agw.core.errors import ApiError
from agw.core.pagination import decode_cursor, encode_cursor
from agw.core.security import hash_secret, new_token, parse_token, verify_secret
from agw.core.time import utcnow
from agw.policy.engine import Principal, evaluate_tool_call

SERVICE_ID = uuid.uuid4()
AGENT_ID = uuid.uuid4()
WORKSPACE_ID = uuid.uuid4()


def _principal() -> Principal:
    return Principal(
        kind="agent",
        id=AGENT_ID,
        workspace_id=WORKSPACE_ID,
        permissions=frozenset({"grant:read"}),
        role="agent:executor",
        agent_id=AGENT_ID,
        ceiling={"services": {str(SERVICE_ID): {"tools": ["search"]}}},
    )


def _agent():
    return SimpleNamespace(
        id=AGENT_ID, workspace_id=WORKSPACE_ID, status="active", ceiling={}
    )


def _service():
    return SimpleNamespace(id=SERVICE_ID, workspace_id=WORKSPACE_ID)


def _grant(tools: list[str], constraints: dict | None = None):
    return SimpleNamespace(
        status="active",
        tools=tools,
        arg_constraints=constraints or {},
        expires_at=None,
    )


def test_policy_allows_granted_tool():
    decision = evaluate_tool_call(
        _principal(),
        agent=_agent(),
        service=_service(),
        tool_name="search",
        grant=_grant(["search"]),
        arguments={"q": "invoice"},
        now=utcnow(),
    )
    assert decision.allowed


def test_policy_denies_unlisted_tool():
    decision = evaluate_tool_call(
        _principal(),
        agent=_agent(),
        service=_service(),
        tool_name="delete",
        grant=_grant(["search"]),
        arguments={},
        now=utcnow(),
    )
    assert not decision.allowed
    assert decision.code == "tool_not_allowed"


def test_policy_denies_expired_grant():
    grant = _grant(["search"])
    grant.expires_at = utcnow() - timedelta(seconds=1)
    decision = evaluate_tool_call(
        _principal(),
        agent=_agent(),
        service=_service(),
        tool_name="search",
        grant=grant,
        arguments={},
        now=utcnow(),
    )
    assert not decision.allowed


def test_argument_constraints():
    decision = evaluate_tool_call(
        _principal(),
        agent=_agent(),
        service=_service(),
        tool_name="search",
        grant=_grant(["search"], {"search": {"tenant": {"equals": "acme"}}}),
        arguments={"tenant": "other"},
        now=utcnow(),
    )
    assert not decision.allowed
    assert decision.code == "arg_rejected"


def test_api_key_format_and_hash():
    token, prefix, secret = new_token("live")
    assert token.startswith("agw_live_")
    parsed = parse_token(token, "live")
    assert parsed == (prefix, secret)
    hashed = hash_secret(secret)
    assert verify_secret(hashed, secret)
    assert not verify_secret(hashed, "wrong")


def test_cursor_rejects_tampering():
    secret = "test-secret"
    cursor = encode_cursor({"v": 1, "o": 50, "qh": "abc"}, secret)
    assert decode_cursor(cursor, secret)["o"] == 50
    with pytest.raises(ApiError):
        decode_cursor(cursor + "x", secret)
