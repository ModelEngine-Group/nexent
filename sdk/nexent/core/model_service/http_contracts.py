# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""HTTP boundary contracts; credentials are resolved only by the sender."""

import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import unquote, urlsplit, urlunsplit

from nexent.core.model_service.profiles.resolved_profile import CredentialReference


CONTROL_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
AUTH_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key"})
HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def validate_headers(headers: dict[str, str], *, credentials: bool = False) -> dict[str, str]:
    """Reject invalid/control headers without exposing their values."""
    if not isinstance(headers, dict):
        raise ValueError("Invalid model HTTP headers")
    result = {}
    for name, value in headers.items():
        if (
            not isinstance(name, str)
            or not HEADER_NAME.fullmatch(name)
            or not isinstance(value, str)
            or any(ord(character) < 32 or ord(character) >= 127 for character in value)
            or name.lower() in result
            or name.lower() in CONTROL_HEADERS
            or (not credentials and name.lower() in AUTH_HEADERS)
        ):
            raise ValueError("Invalid model HTTP headers")
        result[name.lower()] = value
    return result


def model_request_url(base_url: str, relative_path: str) -> str:
    """Preserve the API root and query without guessing a provider prefix."""
    if not isinstance(base_url, str) or not isinstance(relative_path, str):
        raise ValueError("Invalid model HTTP URL")
    if any(character.isspace() or ord(character) < 32 for character in base_url + relative_path):
        raise ValueError("Invalid model HTTP URL")
    try:
        base, relative = urlsplit(base_url), urlsplit(relative_path)
        invalid_port = base.port is not None and not 0 < base.port < 65536
    except ValueError:
        raise ValueError("Invalid model HTTP URL") from None
    if (
        base.scheme not in {"http", "https"}
        or not base.hostname
        or base.username is not None
        or base.password is not None
        or base.fragment
        or invalid_port
        or relative.scheme
        or relative.netloc
        or relative.query
        or relative.fragment
        or not relative.path
        or relative.path.startswith("//")
        or "\\" in unquote(relative.path)
        or any(part in {"", ".", ".."} for part in unquote(relative.path).lstrip("/").split("/"))
    ):
        raise ValueError("Invalid model HTTP URL")
    return urlunsplit(
        (base.scheme, base.netloc, base.path.rstrip("/") + "/" + relative.path.lstrip("/"), base.query, "")
    )


@dataclass(frozen=True)
class PreparedHttpRequest:
    """Store a detached serialized body, never a mutable caller-owned payload."""

    request_id: str
    method: str
    base_url: str = field(repr=False)
    relative_path: str
    headers: dict[str, str] = field(repr=False)
    credential_ref: CredentialReference
    json_body: dict = field(repr=False)
    timeout_seconds: float
    ssl_verify: bool
    stream_protocol: str | None = None
    url: str = field(init=False, repr=False)
    body_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self):
        if (
            not isinstance(self.request_id, str)
            or not self.request_id.strip()
            or self.method not in {"POST", "GET"}
            or type(self.timeout_seconds) not in {int, float}
            or not 0 < self.timeout_seconds < float("inf")
            or type(self.ssl_verify) is not bool
            or self.stream_protocol not in {None, "sse"}
            or not isinstance(self.credential_ref, CredentialReference)
            or not isinstance(self.json_body, dict)
        ):
            raise ValueError("Invalid prepared model HTTP request")
        try:
            body = json.dumps(self.json_body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ValueError("Invalid model HTTP body") from None
        object.__setattr__(self, "body_bytes", body)
        object.__setattr__(self, "json_body", MappingProxyType(json.loads(body)))
        object.__setattr__(self, "headers", MappingProxyType(validate_headers(self.headers)))
        object.__setattr__(self, "url", model_request_url(self.base_url, self.relative_path))


@dataclass(frozen=True)
class RawHttpResponse:
    status_code: int
    headers: dict[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    def error_details(self) -> dict:
        """Extract display details at the shared HTTP boundary, never retry policy."""
        text = self.body.decode("utf-8", errors="replace")
        try:
            body = json.loads(text)
        except (ValueError, RecursionError):
            body = None
        detail = body.get("error", body) if isinstance(body, dict) else body
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("detail")
            if isinstance(message, list):
                message = "; ".join(item["msg"] for item in message
                                    if isinstance(item, dict) and isinstance(item.get("msg"), str))
            if not isinstance(message, str):
                message = text
            code, parameter = detail.get("code"), detail.get("param")
        else:
            message = detail if isinstance(detail, str) else text
            code, parameter = None, None
        # Strip known request credentials before bounding or publishing the detail.
        for value in sorted(set(self.sensitive_values), key=len, reverse=True):
            if value:
                message = message.replace(value, "[redacted]")
        message = re.sub(r"(?i)\bBearer\s+[^\s\"'<>]+", "Bearer [redacted]", message)
        message = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", message)
        message = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", message).split())[:2048]
        return {"message": message, "code": code if isinstance(code, str) else None,
                "parameter": parameter if isinstance(parameter, str) else None}


class ModelTransportError(Exception):
    """Safe common error with private response bytes available to adapters."""

    def __init__(self, category: str, *, response: RawHttpResponse | None = None):
        self.category = category
        self.response = response
        super().__init__(category)
