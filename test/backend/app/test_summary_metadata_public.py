# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SUM-META-02 preserve manual summary HTTP contracts and actor scope."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from management.api.knowledge_base import knowledge_summary as module
from nexent.storage.errors import DeadlineExceeded, NotFound, ScopeDenied


@pytest.fixture
def public(mocker):
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.authenticate] = lambda: SimpleNamespace(
        user_id="reader", tenant_id="tenant-a"
    )
    mocker.patch.object(
        module, "get_current_user_id", return_value=("reader", "tenant-a")
    )
    target = mocker.patch.object(
        module, "resource_read_tenant", return_value="tenant-b"
    )
    read = mocker.patch.object(
        module, "read_summary", return_value={"status": "success", "summary": None}
    )
    update = mocker.patch.object(
        module, "update_summary", return_value={"status": "success", "summary": "New"}
    )
    with TestClient(app) as client:
        yield SimpleNamespace(**locals())


def test_read_keeps_response_actual_actor_and_explicit_target(public):
    s = public
    response = s.client.get("/summary/kb/summary")
    assert response.status_code == 200 and response.json() == s.read.return_value
    args = s.read.await_args
    assert args.args[0] == "kb" and (args.args[1].user_id, args.args[1].tenant_id) == (
        "reader",
        "tenant-a",
    )
    assert args.kwargs["target_tenant"] == "tenant-b"


def test_manual_update_keeps_body_and_actor(public):
    s = public
    response = s.client.post("/summary/kb/summary", json={"summary_result": "New"})
    assert response.status_code == 200 and response.json() == s.update.return_value
    args = s.update.await_args
    assert args.args[:2] == ("kb", "New") and (
        args.args[2].user_id,
        args.args[2].tenant_id,
    ) == ("reader", "tenant-a")


@pytest.mark.parametrize(
    "method,error,status",
    [
        (method, error, status)
        for method in ("get", "post")
        for error, status in [
            (ScopeDenied(), 403),
            (NotFound(), 404),
            (DeadlineExceeded(), 500),
            (ValueError("broken"), 500),
        ]
    ],
)
def test_failed_summary_is_never_an_empty_success(public, method, error, status):
    s = public
    if method == "get":
        s.read.side_effect = error
        response = s.client.get("/summary/kb/summary")
    else:
        s.update.side_effect = error
        response = s.client.post("/summary/kb/summary", json={"summary_result": "New"})
    assert response.status_code == status


def test_expired_post_identity_does_not_write(public, mocker):
    mocker.patch.object(
        module, "get_current_user_id", side_effect=module.TokenExpiredError("expired")
    )
    assert (
        public.client.post(
            "/summary/kb/summary", json={"summary_result": "New"}
        ).status_code
        == 401
    )
    public.update.assert_not_awaited()


def test_inventory_scope_rejection_preserves_http_status(public):
    public.target.side_effect = HTTPException(status_code=403, detail="Scope denied")
    response = public.client.get("/summary/kb/summary")
    assert response.status_code == 403 and response.json()["detail"] == "Scope denied"
    public.read.assert_not_awaited()


def test_missing_unscoped_summary_keeps_existing_500_contract(public):
    public.target.return_value = None
    public.read.side_effect = NotFound()
    response = public.client.get("/summary/kb/summary")
    assert response.status_code == 500
    assert (
        response.json()["detail"]
        == "Failed to get knowledge base summary: Failed to get summary: Unable to get summary for index kb"
    )
