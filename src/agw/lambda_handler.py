from __future__ import annotations

from agw.lambda_secrets import load_runtime_secrets

load_runtime_secrets()

from mangum import Mangum  # noqa: E402

from agw.main import app  # noqa: E402

handler = Mangum(app, lifespan="auto")
