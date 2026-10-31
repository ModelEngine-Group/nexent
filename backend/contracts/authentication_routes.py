# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared public-entry policy; business authorization stays in each service."""

import re

_PUBLIC = {
    "POST": {"/user/signup", "/user/signin", "/user/refresh_token", "/user/logout",
             "/user/oauth/complete", "/user/cas/callback", "/user/cas/logout_callback"},
    "GET": {"/user/service_health", "/user/oauth/config", "/user/oauth/providers",
            "/user/oauth/authorize", "/user/oauth/callback", "/user/oauth/pending",
            "/user/cas/config", "/user/cas/login", "/user/cas/callback", "/user/cas/renew",
            "/user/cas/renew_callback", "/nb/v1/health", "/user/current_user_info"},
}


def canonical_path(path: str) -> str:
    return path[4:] if path.startswith("/api/") else path


def is_public_request(method: str, path: str) -> bool:
    path = canonical_path(path)
    if path in _PUBLIC.get(method, set()):
        return True
    return method == "GET" and bool(
        re.fullmatch(r"/nb/a2a/[^/]+/\.well-known/agent-card\.json", path)
        or re.fullmatch(r"/share/[^/]+(?:/assets/[^/]+/(?:download|preview))?", path)
    )


def is_runtime_service_request(method: str, path: str) -> bool:
    path = canonical_path(path)
    return method == "POST" and bool(
        path in {"/agent/internal/northbound/run", "/agent-evaluations/internal/run",
                 "/agent-evaluations/internal/trial-run"}
        or re.fullmatch(r"/agent/internal/northbound/stop/[^/]+", path)
    )
