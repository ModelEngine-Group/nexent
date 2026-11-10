# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep local telemetry content within JSON DTOs and remove credential fields."""

import json


_CREDENTIAL_FIELDS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "secret_key",
        "client_secret",
        "password",
        "passwd",
        "private_key",
        "credential",
        "credentials",
        "otlp_headers",
        "headers",
    }
)


def safe_local_content(value):
    def clean(item, depth=0):
        if depth > 64:
            raise ValueError("Local content nesting exceeds 64 levels")
        if item is None or type(item) in {str, int, float, bool}:
            return item
        if isinstance(item, dict):
            result = {}
            for key, value in item.items():
                if not isinstance(key, str):
                    raise ValueError("Local content keys must be strings")
                if key.lower().replace("-", "_") not in _CREDENTIAL_FIELDS:
                    result[key] = clean(value, depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            return [clean(value, depth + 1) for value in item]
        raise ValueError("Local content must be a JSON DTO")

    cleaned = clean(value)
    return cleaned if isinstance(cleaned, str) else json.dumps(cleaned, ensure_ascii=False, allow_nan=False)
