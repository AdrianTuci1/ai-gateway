from __future__ import annotations

from agw.config import Runtime, Settings
from agw.core.errors import persistent_runtime_required


def feature_enabled(settings: Settings, feature: str) -> bool:
    return bool(settings.features.get(feature, False))


def require_feature(settings: Settings, feature: str) -> None:
    if not feature_enabled(settings, feature):
        raise persistent_runtime_required(feature)


def runtime_payload(settings: Settings) -> dict[str, object]:
    return {
        "runtime": settings.runtime.value,
        "features": settings.features,
        "limits": {
            "tool_timeout_seconds": settings.tool_timeout_seconds,
            "mcp_stream_max_seconds": settings.mcp_stream_max_seconds,
        },
    }


def is_persistent(settings: Settings) -> bool:
    return settings.runtime == Runtime.PERSISTENT
