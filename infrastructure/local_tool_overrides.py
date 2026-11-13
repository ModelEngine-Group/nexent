# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Carry request-owned tool parameters in a scope-bound encrypted reference."""

import base64
import hmac
import json

from cryptography.fernet import Fernet, InvalidToken

from contracts.constants import environment

PREFIX = "agentos-local-tool-parameters-v1:"
_DOMAIN = b"nexent/agentos/local-tool-parameters/v1"


def _cipher() -> Fernet:
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), _DOMAIN, "sha256")
    return Fernet(base64.urlsafe_b64encode(key))


def seal_tool_overrides(scope: tuple, overrides: dict) -> str:
    """Bind overrides to the caller and the immutable persisted tool reference."""
    body = json.dumps({"scope": list(scope), "parameters": overrides}, ensure_ascii=False, allow_nan=False).encode()
    return PREFIX + _cipher().encrypt(body).decode("ascii")


def open_tool_overrides(reference: str, scope: tuple) -> dict:
    """Reject moved or modified references before exposing their parameters."""
    if not reference.startswith(PREFIX):
        raise ValueError("Unsupported local tool parameter reference")
    try:
        body = _cipher().decrypt(reference.removeprefix(PREFIX).encode("ascii"))
        payload = json.loads(body)
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ValueError("Invalid local tool parameter reference") from exc
    if (not isinstance(payload, dict) or payload.get("scope") != list(scope)
            or not isinstance(payload.get("parameters"), dict)):
        raise ValueError("Local tool parameter reference is outside the run scope")
    return payload["parameters"]
