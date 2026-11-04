from __future__ import annotations

import json
import os

_FIELDS = {
    "secret_key": "AGW_SECRET_KEY",
    "database_url": "AGW_DATABASE_URL",
    "bootstrap_token": "AGW_BOOTSTRAP_TOKEN",
}


def load_runtime_secrets() -> None:
    """Populate runtime environment variables from a Secrets Manager JSON secret.

    The Lambda entrypoints call this before importing the application so that
    `Settings` sees the values. Explicitly provided environment variables win.
    """
    arn = os.environ.get("AGW_APP_SECRET_ARN")
    if not arn:
        return
    import boto3

    region = os.environ.get("AGW_AWS_REGION") or os.environ.get("AWS_REGION")
    client = boto3.client("secretsmanager", region_name=region)
    payload = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
    for field, env_name in _FIELDS.items():
        value = payload.get(field)
        if value:
            os.environ.setdefault(env_name, value)
