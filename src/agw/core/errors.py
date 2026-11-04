from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.headers = headers or {}
        super().__init__(message)

    def body(self, trace_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.detail:
            payload.update(self.detail)
        if trace_id:
            payload["trace_id"] = trace_id
        return payload


def not_found(resource: str) -> ApiError:
    return ApiError(404, "not_found", f"{resource} does not exist")


def forbidden(code: str = "forbidden", message: str = "permission denied") -> ApiError:
    return ApiError(403, code, message)


def unauthenticated(message: str = "authentication required") -> ApiError:
    return ApiError(
        401,
        "unauthenticated",
        message,
        headers={"WWW-Authenticate": 'Bearer realm="agw", enroll="/v1/enroll"'},
    )


def enrollment_required() -> ApiError:
    return ApiError(
        401,
        "enrollment_required",
        "no credential presented",
        detail={"discovery": "/.well-known/agw"},
        headers={"WWW-Authenticate": 'Bearer realm="agw", enroll="/v1/enroll"'},
    )


def persistent_runtime_required(requirement: str) -> ApiError:
    return ApiError(
        409,
        "persistent_runtime_required",
        f"{requirement} requires the persistent runtime",
        detail={"requirement": requirement},
    )


def feature_unavailable(feature: str) -> ApiError:
    return ApiError(501, "feature_unavailable", f"{feature} is not implemented yet")
