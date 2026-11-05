# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fixed upstream selection and proxy header policy."""

from gateway.exposure.registry import default_registry
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_UNTRUSTED_HEADERS = {
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-real-ip", "x-user-id", "x-tenant-id", "x-internal-token",
    "x-authenticated-user", "x-authenticated-tenant",
}


def select_upstream(method: str, path: str, *, transport="http") -> str | None:
    """Resolve only a declared public method/path/transport to a fixed service."""
    match = default_registry().match(method, path, transport=transport)
    return match.target if match else None


def filtered_headers(headers, *, request=False):
    """Preserve duplicate headers while removing hop and untrusted identity fields."""
    headers = list(headers)
    blocked = set(_HOP_HEADERS)
    for name, value in headers:
        if name.lower() == "connection":
            blocked.update(item.strip().lower() for item in value.split(","))
    if request:
        blocked.update(_UNTRUSTED_HEADERS)
    return [(name, value) for name, value in headers if name.lower() not in blocked
            and not (request and (name.lower().startswith("x-internal-") or name.lower().startswith("x-nexent-")))]
