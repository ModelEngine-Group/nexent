# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep local telemetry content within JSON DTOs and remove credential fields."""

import json
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from types import FunctionType, MethodType
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

from pydantic import BaseModel


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

_URL_PATTERN = re.compile(r"https?://[^\s<>\"'`\\，。；]+", re.IGNORECASE)
_URL_CREDENTIAL_FIELDS = _CREDENTIAL_FIELDS | {
    "x_amz_signature", "x_amz_credential", "x_amz_security_token",
    "awsaccesskeyid", "signature", "securitytoken", "x_goog_signature",
    "x_goog_credential", "googleaccessid", "ossaccesskeyid", "x_oss_signature",
    "x_oss_credential", "sig", "token", "auth", "key",
}
_URL_REDACTED = "REDACTED_CREDENTIAL"


def _redact_url_parameters(query, depth):
    parts = []
    for part in query.split("&"):
        key, separator, value = part.partition("=")
        normalized = unquote_plus(key, errors="strict").lower().replace("-", "_")
        if separator and normalized in _URL_CREDENTIAL_FIELDS:
            parts.append(f"{key}={_URL_REDACTED}")
            continue
        decoded = unquote_plus(value, errors="strict")
        cleaned = _redact_urls(decoded, depth + 1) if _URL_PATTERN.search(decoded) else decoded
        parts.append(f"{key}={quote(cleaned, safe='')}" if cleaned != decoded else part)
    return "&".join(parts)


def _redact_urls(text, depth=0):
    """Sanitize URL credentials in a detached payload, including encoded proxy URLs."""
    if depth > 8:
        raise ValueError("Local URL nesting exceeds 8 levels")

    def replace(match):
        original = match.group()
        value, suffix = original, ""
        # Preserve surrounding prose and Markdown punctuation outside the URL.
        while value and (
            value[-1] in ",.;"
            or (value[-1] == ")" and value.count(")") > value.count("("))
            or (value[-1] == "]" and value.count("]") > value.count("["))
            or (value[-1] == "}" and value.count("}") > value.count("{"))
        ):
            suffix, value = value[-1] + suffix, value[:-1]
        parsed = urlsplit(value)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = f"{_URL_REDACTED}@{netloc.rsplit('@', 1)[1]}"
        query = _redact_url_parameters(parsed.query, depth)
        fragment = _redact_url_parameters(parsed.fragment, depth) if "=" in parsed.fragment else parsed.fragment
        if (netloc, query, fragment) == (parsed.netloc, parsed.query, parsed.fragment):
            return original
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment)) + suffix

    return _URL_PATTERN.sub(replace, text)


def local_capture_enabled(manager):
    """Use concrete configuration values; permissive test doubles must stay disabled."""
    config = getattr(manager, '_config', None)
    sink = getattr(config, 'provider', None)
    return (getattr(manager, 'is_enabled', False) is True
            and getattr(config, 'export_traces', False) is True
            and type(sink) is str and sink == 'local_file')


def local_content_value(value):
    """Convert supported SDK DTOs without inspecting arbitrary runtime services."""
    def clean(item, depth=0):
        if depth > 64:
            raise ValueError("Local content nesting exceeds 64 levels")
        if isinstance(item, Enum):
            return clean(item.value, depth + 1)
        if isinstance(item, str):
            return _redact_urls(item)
        if item is None or type(item) in {int, float, bool}:
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
        if isinstance(item, BaseModel):
            return clean(item.model_dump(mode='python', exclude={'raw'}), depth + 1)
        if is_dataclass(item) and not isinstance(item, type):
            return clean({field.name: getattr(item, field.name) for field in fields(item)
                          if field.name != 'raw'}, depth + 1)
        if isinstance(item, (FunctionType, MethodType)):
            return {'type': 'callable_reference', 'name': item.__name__,
                    'implementation': f'{item.__module__}.{item.__qualname__}'}
        from smolagents.tools import BaseTool

        from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper

        if isinstance(item, (BaseTool, SubAgentToolWrapper)):
            return {'type': 'tool_reference', 'name': str(item.name),
                    'implementation': f'{type(item).__module__}.{type(item).__qualname__}'}
        raise ValueError("Local content must be a JSON DTO")

    return clean(value)


def safe_local_content(value):
    cleaned = local_content_value(value)
    return cleaned if isinstance(cleaned, str) else json.dumps(cleaned, ensure_ascii=False, allow_nan=False)
