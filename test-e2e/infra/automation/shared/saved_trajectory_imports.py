# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned persistent import HTTP fixtures; authentication is the controlled boundary."""

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient
from ops.api import trajectory as api
from ops.services.trajectory.saved_imports import SavedImports
from trajectory_exchange import http_app


@contextmanager
def started_app(monkeypatch):
    from contracts.constants import environment as config
    from ops.api.application import create_app

    with monkeypatch.context() as patch:
        patch.setattr(config, "TRAJECTORY_READ_ENABLED", False)
        patch.setattr(config, "MONITORING_PROVIDER", "otlp")
        app = create_app()
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client, app=app, manager=app.state.thread_manager
            )
        assert app.state.thread_manager.snapshot().active_count == 0


@contextmanager
def saved_http(monkeypatch, root, source=None, *, real_startup=False):
    service = (
        started_app(monkeypatch) if real_startup else http_app(monkeypatch, source)
    )
    with service as http, monkeypatch.context() as patch:

        def context(header):
            if not header:
                return None, None, ()
            if header == "user":
                return "reader", "local", ("USER",)
            if header == "peer":
                return "peer", "local", ("OPS",)
            if header == "other":
                return "admin", "other", ("SU",)
            return "admin", "local", ("OPS",)

        patch.setattr(api, "get_current_user_context", context)
        patch.setattr(api, "configured_store", lambda: SavedImports(root))
        yield http


def upload_saved(http, raw, actor="admin"):
    return http.client.post(
        "/trajectory/imports",
        files={"file": ("轨迹.zip", raw, "application/zip")},
        headers={"Authorization": actor} if actor else {},
    )


def call(http, method, path="", actor="admin", **kwargs):
    return http.client.request(
        method,
        "/trajectory/imports" + path,
        headers={"Authorization": actor} if actor else {},
        **kwargs,
    )
