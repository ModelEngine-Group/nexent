# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""End-to-end proxy tests against the standalone AIDP mock over real HTTP.

These tests exercise the Nexent route -> service -> HTTP -> AIDP contract
without a database or browser, complementing the mocked unit tests. They use
the real ``http_client_manager`` from the installed SDK.
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import uvicorn
from ext_components.aidp.apps import aidp_mgmt_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.utils.app_factory import register_exception_handlers

MOCK_PATH = Path(__file__).parent / "mock_servers" / "aidp_mgmt_mock_server.py"
MOCK_API_KEY = "mock-aidp-key"
USER_ID = "user-test"
TENANT_ID = "tenant-test"
KB_ONE = "aidp-kb-faq"
KB_TWO = "aidp-kb-04"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(aidp_mgmt_app.aidp_mgmt_router)
    register_exception_handlers(app)
    return TestClient(app)


def _bearer() -> dict:
    return {"Authorization": "Bearer fake-token"}


@pytest.fixture
def aidp_mock_url(tmp_path, monkeypatch):
    """Run the AIDP mock on a free port with isolated persisted state."""
    monkeypatch.setenv("AIDP_MOCK_STATE_FILE", str(tmp_path / "mock-state.json"))
    module_name = "aidp_mgmt_mock_integration"
    spec = importlib.util.spec_from_file_location(module_name, MOCK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(module.app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("AIDP mock did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sys.modules.pop(module_name, None)


@pytest.fixture
def configured_client(aidp_mock_url, monkeypatch):
    monkeypatch.setattr(aidp_mgmt_app, "AIDP_SERVER_URL", aidp_mock_url)
    monkeypatch.setattr(aidp_mgmt_app, "AIDP_API_KEY", MOCK_API_KEY)
    monkeypatch.setattr(
        aidp_mgmt_app.auth_utils_module,
        "get_current_user_id",
        lambda *_a, **_kw: (USER_ID, TENANT_ID),
    )
    monkeypatch.setattr(
        aidp_mgmt_app.perms,
        "require_permission",
        MagicMock(return_value=MagicMock(permission="EDIT")),
    )
    return _client()


def test_kb_sensitive_toggle_round_trip_over_http(aidp_mock_url):
    from ext_components.aidp.services.aidp_service import (
        create_aidp_kb_impl,
        get_aidp_kb_impl,
        update_aidp_kb_impl,
    )

    created = create_aidp_kb_impl(
        aidp_mock_url,
        MOCK_API_KEY,
        {
            "name": "敏感词开关验收",
            "description": "desc",
            "embedding_model": "bge-m3",
            "caption_enable": 0,
            "is_exist_graph": False,
            "sensitive_intercept_enable": 0,
        },
    )
    kds_id = str(created["kds_id"])
    assert get_aidp_kb_impl(aidp_mock_url, MOCK_API_KEY, kds_id)[
        "sensitive_intercept_enable"
    ] == 0

    update_aidp_kb_impl(
        aidp_mock_url, MOCK_API_KEY, kds_id, {"sensitive_intercept_enable": 1}
    )
    assert get_aidp_kb_impl(aidp_mock_url, MOCK_API_KEY, kds_id)[
        "sensitive_intercept_enable"
    ] == 1

    update_aidp_kb_impl(
        aidp_mock_url, MOCK_API_KEY, kds_id, {"sensitive_intercept_enable": 0}
    )
    assert get_aidp_kb_impl(aidp_mock_url, MOCK_API_KEY, kds_id)[
        "sensitive_intercept_enable"
    ] == 0


def test_sensitive_words_are_isolated_per_kb_over_http(configured_client):
    client = configured_client
    headers = _bearer()
    base = "/aidp-mgmt/knowledge-bases"
    kb1 = f"{base}/{KB_ONE}/sensitive-words"
    kb2 = f"{base}/{KB_TWO}/sensitive-words"

    listed1 = client.get(kb1, headers=headers, params={"page": 1, "page_size": 10})
    listed2 = client.get(kb2, headers=headers, params={"page": 1, "page_size": 10})
    assert listed1.status_code == 200
    assert listed2.status_code == 200
    body1 = listed1.json()
    body2 = listed2.json()
    assert "can_manage" not in body1
    assert "next_link" in body1
    assert body1["total_count"] >= 3
    ids1 = {row["id"] for row in body1["value"]}
    ids2 = {row["id"] for row in body2["value"]}
    assert ids1 and ids2 and not (ids1 & ids2)

    created1 = client.post(
        kb1,
        headers=headers,
        json={"word": "接口验收词", "mode": "BLACK", "description": "kb1"},
    )
    assert created1.status_code == 201
    assert set(created1.json()) == {"id"}
    word_id = created1.json()["id"]
    assert all(row["id"] != word_id for row in body2["value"])

    created2 = client.post(
        kb2,
        headers=headers,
        json={"word": "接口验收词", "mode": "BLACK", "description": "kb2"},
    )
    assert created2.status_code == 201

    duplicate = client.post(
        kb1,
        headers=headers,
        json={"word": "接口验收词", "mode": "BLACK", "description": "dup"},
    )
    assert duplicate.status_code == 502
    duplicate_body = duplicate.json()
    assert duplicate_body["message"] == "Sensitive word already exists in this knowledge base"
    assert duplicate_body["details"]["upstream_code"] == "1022"

    builtin_blocked = client.patch(
        f"{kb1}/sw-faq-builtin-black",
        headers=headers,
        json={"description": "不允许修改"},
    )
    assert builtin_blocked.status_code == 502
    assert builtin_blocked.json()["details"]["upstream_code"] == "1008"
    assert "read-only" in builtin_blocked.json()["message"]

    wrong_kb = client.get(f"{kb1}/{created2.json()['id']}", headers=headers)
    assert wrong_kb.status_code == 502
    assert wrong_kb.json()["details"]["upstream_code"] == "1004"
    assert "not found in knowledge base" in wrong_kb.json()["message"]

    updated = client.patch(
        f"{kb1}/{word_id}",
        headers=headers,
        json={"mode": "WHITE"},
    )
    assert updated.status_code == 200
    assert updated.json() == {}

    filtered = client.get(
        kb1,
        headers=headers,
        params={"page": 1, "page_size": 10, "mode": "WHITE", "keyword": "接口验收"},
    )
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()["value"]] == [word_id]
    assert filtered.json()["next_link"] is None

    deleted = client.delete(f"{kb1}/{word_id}", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""

    # Deleting in kb1 leaves the same word in kb2 untouched.
    assert client.get(f"{kb2}/{created2.json()['id']}", headers=headers).status_code == 200
