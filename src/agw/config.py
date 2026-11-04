from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Runtime(str, Enum):
    PERSISTENT = "persistent"
    REQUEST_RESPONSE = "request_response"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGW_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    runtime: Runtime = Runtime.PERSISTENT
    db_backend: Literal["sql", "dynamodb"] = "sql"
    database_url: str = "sqlite+aiosqlite:///./agw.db"
    db_driver: Literal["asyncpg", "http", "sqlite"] = "sqlite"
    db_pool_size: int = 5
    db_pool_mode: Literal["pooled", "null"] = "pooled"
    dynamodb_table: str = "ai-gateway"
    dynamodb_endpoint_url: str | None = None
    dynamodb_region: str | None = None
    public_base_url: str = "http://127.0.0.1:8080"
    app_secret_arn: str | None = None
    aws_region: str | None = None

    secret_key: SecretStr = SecretStr("dev-insecure-change-me")
    session_ttl_hours: int = 12
    enrollment_token_ttl_minutes: int = 15
    enrollment_token_max_ttl_minutes: int = 1440
    device_code_ttl_seconds: int = 600
    device_code_interval_seconds: int = 5

    tool_timeout_seconds: int = 300
    mcp_stream_max_seconds: int = 900

    bootstrap_enabled: bool = False
    bootstrap_token: SecretStr | None = None
    signup_enabled: bool = True
    identity_invite_ttl_hours: int = 168
    password_auth_enabled: bool = True
    dev_auth: bool = False
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_allowed_domains: str = "gmail.com"
    oidc_state_ttl_seconds: int = 600
    auto_create: bool = False
    enable_stdio: bool = False

    ca_enabled: bool = True
    ca_dir: Path = Path("./.agw-ca")
    agent_cert_ttl_hours: int = 24
    ca_cert_ttl_days: int = 3650

    ui_enabled: bool = True
    log_level: str = "info"

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if self.tool_timeout_seconds > self.mcp_stream_max_seconds:
            raise ValueError("tool_timeout_seconds cannot exceed mcp_stream_max_seconds")
        if self.runtime == Runtime.REQUEST_RESPONSE and self.enable_stdio:
            raise ValueError("stdio connectors require the persistent runtime")
        if self.bootstrap_enabled and self.bootstrap_token is None:
            raise ValueError("bootstrap_enabled requires bootstrap_token")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def uses_dynamodb(self) -> bool:
        return self.db_backend == "dynamodb"

    @property
    def features(self) -> dict[str, bool]:
        persistent = self.runtime == Runtime.PERSISTENT
        return {
            "mcp_sse": persistent,
            "mcp_sessions": persistent,
            "stdio": persistent and self.enable_stdio,
            "a2a_stream": persistent,
            "a2a_push": persistent,
        }

    @property
    def session_secret(self) -> str:
        return self.secret_key.get_secret_value()
