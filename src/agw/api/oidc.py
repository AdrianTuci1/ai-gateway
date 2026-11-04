from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote, urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from agw.api.auth import _base_url
from agw.api.deps import get_settings, get_store
from agw.audit.service import record
from agw.config import Settings
from agw.core.errors import ApiError, not_found
from agw.core.security import create_session_token, new_opaque
from agw.core.time import utcnow
from agw.store.base import Store

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

_jwks = jwt.PyJWKClient(GOOGLE_JWKS_URL)
_STATE_TYPE = "oidc_state"


def _client_secret(settings: Settings) -> str | None:
    if settings.google_client_secret is None:
        return None
    return settings.google_client_secret.get_secret_value()


def _configured(settings: Settings) -> bool:
    return bool(settings.google_client_id and _client_secret(settings))


def _redirect_uri(request: Request, settings: Settings) -> str:
    return f"{_base_url(request, settings)}/v1/auth/oidc/google/callback"


def _allowed_domains(settings: Settings) -> set[str]:
    return {
        domain.strip().lower()
        for domain in settings.google_allowed_domains.split(",")
        if domain.strip()
    }


def _login_url(request: Request, settings: Settings, error: str | None = None) -> str:
    base = _base_url(request, settings)
    if error:
        return f"{base}/?sso_error={quote(error)}"
    return f"{base}/"


async def exchange_google_code(
    settings: Settings, *, code: str, redirect_uri: str
) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": _client_secret(settings),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise ApiError(401, "oidc_exchange_failed", "Google rejected the sign-in")
    return response.json()


def verify_google_id_token(
    settings: Settings, id_token: str, *, nonce: str
) -> dict:
    try:
        signing_key = _jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            options={"verify_iss": False},
        )
    except jwt.PyJWTError as exc:
        raise ApiError(401, "oidc_token_invalid", "Google returned an invalid token") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ApiError(401, "oidc_token_invalid", "Google returned an invalid issuer")
    if claims.get("nonce") != nonce:
        raise ApiError(401, "oidc_token_invalid", "Google returned an invalid nonce")
    verified = claims.get("email_verified")
    if verified not in (True, "true", "True"):
        raise ApiError(401, "oidc_email_unverified", "the Google e-mail is not verified")
    email = str(claims.get("email") or "").strip().lower()
    if "@" not in email:
        raise ApiError(401, "oidc_token_invalid", "Google returned no e-mail")
    domains = _allowed_domains(settings)
    if domains and email.rsplit("@", 1)[-1] not in domains:
        raise ApiError(403, "oidc_domain_not_allowed", "this Google domain is not allowed")
    return claims


def _state_payload(settings: Settings, *, workspace_slug: str, next_path: str) -> dict:
    now = utcnow()
    return {
        "typ": _STATE_TYPE,
        "ws": workspace_slug,
        "next": next_path,
        "nonce": new_opaque(16),
        "iat": now,
        "exp": now + timedelta(seconds=settings.oidc_state_ttl_seconds),
    }


@router.get("/v1/auth/oidc/google/start")
async def google_start(
    request: Request,
    workspace_slug: str = Query(min_length=2, max_length=80),
    next_path: str = Query(default="/", alias="next"),
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
) -> RedirectResponse:
    if not _configured(settings):
        raise ApiError(503, "oidc_unavailable", "Google sign-in is not configured")
    workspace = await store.get_workspace_by_slug(workspace_slug)
    if workspace is None or workspace.deleted_at is not None:
        raise not_found("workspace")
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    state = jwt.encode(
        _state_payload(
            settings, workspace_slug=workspace.slug, next_path=safe_next
        ),
        settings.session_secret,
        algorithm="HS256",
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(request, settings),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        "access_type": "online",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=303)


@router.get("/v1/auth/oidc/google/callback")
async def google_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
) -> RedirectResponse:
    if not _configured(settings):
        return RedirectResponse(
            _login_url(request, settings, "oidc_unavailable"), status_code=303
        )
    if error is not None:
        return RedirectResponse(
            _login_url(request, settings, "google_denied"), status_code=303
        )
    if not code or not state:
        return RedirectResponse(
            _login_url(request, settings, "invalid_request"), status_code=303
        )
    try:
        payload = jwt.decode(state, settings.session_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return RedirectResponse(
            _login_url(request, settings, "invalid_state"), status_code=303
        )
    if payload.get("typ") != _STATE_TYPE:
        return RedirectResponse(
            _login_url(request, settings, "invalid_state"), status_code=303
        )
    workspace = await store.get_workspace_by_slug(str(payload.get("ws") or ""))
    if workspace is None or workspace.deleted_at is not None:
        return RedirectResponse(
            _login_url(request, settings, "workspace_not_found"), status_code=303
        )

    try:
        tokens = await exchange_google_code(
            settings, code=code, redirect_uri=_redirect_uri(request, settings)
        )
        id_token = str(tokens.get("id_token") or "")
        if not id_token:
            raise ApiError(401, "oidc_token_invalid", "Google returned no ID token")
        claims = verify_google_id_token(
            settings, id_token, nonce=str(payload.get("nonce") or "")
        )
    except ApiError as exc:
        return RedirectResponse(
            _login_url(request, settings, exc.code), status_code=303
        )

    email = str(claims["email"]).strip().lower()
    user = await store.get_user_by_email(email)
    if user is None:
        return RedirectResponse(
            _login_url(request, settings, "no_account"), status_code=303
        )
    membership = await store.get_membership(workspace.id, "user", user.id)
    if membership is None:
        return RedirectResponse(
            _login_url(request, settings, "not_a_member"), status_code=303
        )
    if membership.status == "pending":
        return RedirectResponse(
            _login_url(request, settings, "approval_pending"), status_code=303
        )
    if membership.status == "rejected":
        return RedirectResponse(
            _login_url(request, settings, "signup_rejected"), status_code=303
        )

    token = create_session_token(
        user.id, workspace.id, settings.session_secret, settings.session_ttl_hours
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type="user",
        actor_id=user.id,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        trace_id=request.state.trace_id,
        meta={"method": "google", "email": email},
    )
    await store.commit()
    base = _base_url(request, settings)
    fragment = urlencode(
        {"sso": token, "workspace": workspace.slug, "email": email}
    )
    next_path = str(payload.get("next") or "/")
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    return RedirectResponse(f"{base}{next_path}#{fragment}", status_code=303)
