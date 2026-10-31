# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fixed upstream selection and proxy header policy."""

_RUNTIME_PATHS = (
    "/agent/run", "/agent/nl2agent/run", "/agent/human-interactions",
    "/skills/nl2skill/run", "/agent/stop", "/agent/automations",
    "/conversation", "/share", "/file/preprocess", "/voice/stt/ws", "/voice/tts/ws",
)
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_UNTRUSTED_HEADERS = {
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-real-ip", "x-user-id", "x-tenant-id", "x-internal-token",
    "x-authenticated-user", "x-authenticated-tenant",
}


def select_upstream(method: str, path: str) -> str | None:
    """Route public API paths; internal service endpoints are never exposed."""
    if not (path.startswith("/api/") or path.startswith("/nb/") or path.startswith("/user/")):
        return None
    if "internal" in path.split("/"):
        return None
    path = path.removeprefix("/api") if path.startswith("/api/") else path
    if path == "/nb" or path.startswith("/nb/"):
        return "northbound"
    if not path.startswith("/"):
        return None
    if method == "POST" and path.rstrip("/") == "/file/storage":
        return "runtime"
    if any(path == prefix or path.startswith(prefix + "/") for prefix in _RUNTIME_PATHS):
        return "runtime"
    # Only the /api namespace is a public Management entrypoint.
    return "management"


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
