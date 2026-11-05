# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit legacy HTTP provider for protocol regression tests, never production default."""
from gateway import application
from gateway.security.management_client import lookup_identity


def create_gateway_app(**kwargs):
    settings = kwargs.get("settings")
    if settings is None:
        settings = application.load_settings()
        kwargs["settings"] = settings
    management = (kwargs.get("upstreams") or {}).get("management", settings.management_url)
    app = None
    async def lookup(query):
        return await lookup_identity(query, app.state.client, management, key=settings.signing_key())
    kwargs.setdefault("identity_lookup", lookup)
    app = application.create_gateway_app(**kwargs)
    return app
