# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed authoritative identity lookup without persistence dependencies."""

import json

import httpx

from gateway.protocol.identity import IdentityError, sign_lookup


class IdentityUnavailable(RuntimeError):
    """The authoritative identity service could not be reached safely."""


async def lookup_identity(payload, client, management_url, *, key):
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    try:
        response = await client.post(management_url.rstrip("/") + "/api/internal/identity/resolve",
                                     content=body, headers={"content-type": "application/json",
                                                           "x-nexent-service-token": sign_lookup(body, key=key)},
                                     timeout=httpx.Timeout(10))
    except httpx.RequestError as exc:
        raise IdentityUnavailable("Identity service unavailable") from exc
    if response.status_code in {401, 403}:
        raise IdentityError("Invalid or revoked credential")
    if response.status_code != 200:
        raise IdentityUnavailable("Identity service unavailable")
    try:
        identity = response.json()
        if (not isinstance(identity, dict) or identity.get("kind") != payload["kind"]
                or any(not isinstance(identity.get(k), str) or not identity[k] for k in ("user_id", "tenant_id"))):
            raise ValueError("Invalid identity response")
        if payload["kind"] == "session" and identity["user_id"] != payload["user_id"]:
            raise ValueError("Identity mismatch")
        return identity
    except (ValueError, TypeError) as exc:
        raise IdentityUnavailable("Invalid identity service response") from exc
