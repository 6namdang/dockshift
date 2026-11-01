"""Keep credentials and signed download URLs out of persisted evidence."""

import re

from pydantic import SecretStr

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "access_token",
    "refresh_token",
    "secret",
    "bearer_token",
}


class Redactor:
    def __init__(self, settings):
        self.secrets = []
        for name in (
            "scientific_models_api_key",
            "openai_api_key",
            "ncbi_api_key",
            "structural_api_token",
            "mcp_http_token",
        ):
            value = getattr(settings, name, None)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if value:
                self.secrets.append(value)

    def __call__(self, value):
        if isinstance(value, dict):
            return {
                k: "[redacted]" if k.lower() in SENSITIVE_KEYS else self(v)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
            # Presigned artifact handles are credentials too. Store artifact IDs instead.
            value = re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]+', r"\1?[redacted]", value)
        return value
