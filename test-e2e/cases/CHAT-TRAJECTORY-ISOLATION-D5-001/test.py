# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""PostgreSQL-backed portions of the trajectory authorization risk contract."""

import asyncio
import os
import shutil
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

# isort: split
from contracts.constants import environment
from gateway.identity.downstream import IDENTITY_HEADER, sign_identity
from gateway.identity.middleware import GatewayIdentityMiddleware
from management.db.agent.models import AgentInfo
from nexent.core.concurrency import LanePolicy, ThreadManager
from ops.api import trajectory, trajectory_directory
from ops.db.trajectory.catalog import TrajectoryCatalog
from ops.services.trajectory.primitives import ReferenceStore
from ops.services.trajectory.service import TrajectoryService
from shared.factories.scratch_database import isolated_product_database
from shared.http import assert_status

from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import (
    ConversationMessage,
    ConversationRecord,
)
from infrastructure.rdb.trajectory.capture import CaptureCatalog
from infrastructure.trace.trajectory_store import CaptureIdentity, TrajectoryFileStore

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-ISOLATION-D5-001"),
    pytest.mark.stage("D5"),
    pytest.mark.sec,
]


@pytest.fixture
def pg_scope(tmp_path, monkeypatch):
    if "RESULT_DIR" not in os.environ:
        monkeypatch.setenv("RESULT_DIR", str(tmp_path / "results"))

    def session_identity(user_id, tenant_id, role):
        return {"user_id": user_id, "tenant_id": tenant_id, "roles": [role], "kind": "session"}

    actor_a = session_identity("ops-a", "tenant-a", "OPS")
    actor_b = session_identity("ops-b", "tenant-b", "OPS")
    superuser = session_identity("superuser", "tenant-a", "SU")
    owner_a = session_identity("ordinary-a", "tenant-a", "USER")
    owner_b = session_identity("ordinary-b", "tenant-b", "USER")
    developer = session_identity("developer-a", "tenant-a", "DEV")
    asset_owner = session_identity("asset-a", "tenant-a", "ASSET_OWNER")
    identity_a = CaptureIdentity("tenant-a", "ordinary-a", "123", "7")
    identity_b = CaptureIdentity("tenant-b", "ordinary-b", "456", "8")
    title_a = "fixture-private-title-a"
    title_b = "fixture-private-title-b"
    with isolated_product_database():
        with get_db_session() as session:
            session.execute(text("CREATE SCHEMA IF NOT EXISTS nexent"))
            for table in (UserAccount, UserTenant, ConversationRecord, ConversationMessage, AgentInfo):
                table.__table__.create(session.connection(), checkfirst=True)
            for identity in (actor_a, actor_b, superuser, owner_a, owner_b, developer, asset_owner):
                user, tenant = identity["user_id"], identity["tenant_id"]
                session.add(
                    UserAccount(user_id=user, user_roles=identity["roles"], user_email=f"{user}@example.test")
                )
                session.add(UserTenant(user_id=user, tenant_id=tenant))
            for identity, title in ((identity_a, title_a), (identity_b, title_b)):
                session.add(
                    ConversationRecord(
                        conversation_id=int(identity.conversation_id),
                        conversation_title=title,
                        created_by=identity.owner_user_id,
                        agent_id=int(identity.root_agent_id),
                    )
                )
                session.add(
                    ConversationMessage(
                        conversation_id=int(identity.conversation_id),
                        message_index=0,
                        message_role="user",
                        message_content="fixture-private-chat",
                        created_by=identity.owner_user_id,
                    )
                )

        now = datetime.now(UTC)
        store = TrajectoryFileStore(
            tmp_path / "traces", authorize=CaptureCatalog().authorize, clock=lambda: now
        )
        service = TrajectoryService(store, TrajectoryCatalog(), ReferenceStore())
        monkeypatch.setattr(trajectory, "get_service", lambda: service)
        monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", token_hex(32))
        monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
        manager = ThreadManager(
            "trajectory-isolation",
            {
                "trajectory-read": LanePolicy("trajectory-read", 2, 2),
                "trajectory-cleanup": LanePolicy("trajectory-cleanup", 1, 0),
            },
        )
        manager.start()
        app = FastAPI()
        app.state.thread_manager = manager
        app.add_middleware(GatewayIdentityMiddleware, audience="ops")
        app.include_router(trajectory.router)
        app.include_router(trajectory_directory.router)
        try:
            with TestClient(app) as client:
                yield SimpleNamespace(
                    client=client,
                    store=store,
                    now=now,
                    actor_a=actor_a,
                    actor_b=actor_b,
                    superuser=superuser,
                    owner_a=owner_a,
                    developer=developer,
                    asset_owner=asset_owner,
                    identity_a=identity_a,
                    identity_b=identity_b,
                    title_a=title_a,
                    title_b=title_b,
                )
        finally:
            try:
                asyncio.run(manager.shutdown(timeout=5))
            finally:
                shutil.rmtree(store.root)
        assert manager.snapshot().active_count == 0


def request(scope, actor, method, path, *, params=None, **kwargs):
    url = scope.client.build_request(method, path, params=params).url
    token = sign_identity(actor, "ops", method, url.path, url.query)
    return scope.client.request(method, url, headers={IDENTITY_HEADER: token}, **kwargs)


def add_run(scope, identity, *, age_days=0):
    run_id = str(uuid4())
    finish = scope.now - timedelta(days=age_days)
    started = finish - timedelta(seconds=1)
    values = {
        "tenant.id": identity.tenant_id,
        "nexent.owner_user_id": identity.owner_user_id,
        "conversation.id": identity.conversation_id,
        "session.id": identity.conversation_id,
        "nexent.trace_id": identity.conversation_id,
        "nexent.trajectory_id": run_id,
        "openinference.span.kind": "AGENT",
        "output.value": "fixture-private-trajectory-body",
    }
    span = {
        "traceId": uuid4().hex,
        "spanId": uuid4().hex[:16],
        "kind": 1,
        "name": "agent.run",
        "startTimeUnixNano": str(int(started.timestamp() * 1_000_000_000)),
        "endTimeUnixNano": str(int(finish.timestamp() * 1_000_000_000)),
        "status": {"code": 1},
        "attributes": [{"key": k, "value": {"stringValue": value}} for k, value in values.items()],
    }
    writer = scope.store.start(identity, run_id, str(uuid4()), core_type="smolagents", started_at=started)
    try:
        writer.append(
            [{"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}],
            batch_id=str(uuid4()),
            expected_offset=0,
        )
        writer.finish("completed", finished_at=finish)
    finally:
        writer.close()
    (run_file,) = list(scope.store.root.rglob(f"{run_id}.otlp.jsonl"))
    return run_id, run_file


def test_pg_authorized_actors_cannot_cross_scope_and_revocation_rechecks_cached_reference(pg_scope):
    scope = pg_scope
    run_id, archive = add_run(scope, scope.identity_a)
    add_run(scope, scope.identity_b)
    path = f"/trajectory/conversations/{scope.identity_a.conversation_id}"
    allowed = request(scope, scope.actor_a, "GET", path)
    assert_status(allowed, 200)
    assert allowed.json()["data"]["availability"] == "available"
    assert scope.title_a in allowed.text and scope.title_b not in allowed.text
    directory = "/conversation/agent_groups"
    owner = {"view": "trajectory", "target_user_id": scope.identity_a.owner_user_id}
    groups = request(scope, scope.actor_a, "GET", directory, params=owner)
    assert_status(groups, 200)
    assert [item["group_key"] for item in groups.json()["data"]["items"]] == ["agent:7"]
    assert_status(request(scope, scope.owner_a, "GET", directory, params=owner), 403)
    assert_status(request(scope, scope.actor_b, "GET", directory, params=owner), 404)
    view = request(scope, scope.actor_a, "GET", path + "/snapshot", params={"trajectory_id": run_id})
    assert_status(view, 200)
    content_id = view.json()["data"]["nodes"][0]["output"]["content_id"]
    content = path + "/contents/" + content_id
    foreign_content = f"/trajectory/conversations/{scope.identity_b.conversation_id}/contents/{content_id}"
    body = request(scope, scope.actor_a, "GET", content)
    assert_status(body, 200)
    assert "fixture-private-trajectory-body" in body.text

    denied = [
        (scope.owner_a, path, 403),
        (scope.developer, path, 403),
        (scope.asset_owner, path, 403),
        (scope.actor_b, path, 404),
        (scope.actor_b, content, 422),
        (scope.actor_a, foreign_content, 404),
    ]
    for actor, endpoint, expected in denied:
        response = request(scope, actor, "GET", endpoint)
        assert_status(response, expected)
        assert response.headers["cache-control"] == "private,no-store"
        assert scope.title_a not in response.text and "fixture-private-trajectory-body" not in response.text

    wrong_owner = request(
        scope, scope.actor_a, "GET", path, params={"target_user_id": scope.identity_b.owner_user_id}
    )
    assert_status(wrong_owner, 404)
    foreign_tenant = request(
        scope, scope.superuser, "GET", path, params={"tenant_id": scope.identity_b.tenant_id}
    )
    assert_status(foreign_tenant, 404)
    trusted_scope = request(
        scope, scope.superuser, "GET", path, params={"tenant_id": scope.identity_a.tenant_id}
    )
    assert_status(trusted_scope, 200)

    baseline = archive.read_bytes()
    with get_db_session() as session:
        session.query(UserAccount).filter_by(user_id=scope.actor_a["user_id"]).one().user_roles = ["USER"]
    revoked = request(scope, scope.actor_a, "GET", content)
    assert_status(revoked, 403)
    assert "fixture-private-trajectory-body" not in revoked.text
    assert archive.read_bytes() == baseline


def test_pg_tenant_move_revokes_old_reads_without_rebinding_the_trajectory(pg_scope):
    scope = pg_scope
    run_id, archive = add_run(scope, scope.identity_a)
    path = f"/trajectory/conversations/{scope.identity_a.conversation_id}"
    archive_before = archive.read_bytes()
    manifest_before = (archive.parent / "meta.json").read_bytes()
    with get_db_session() as session:
        session.query(UserTenant).filter_by(user_id=scope.identity_a.owner_user_id).one().tenant_id = "tenant-b"

    for actor in (scope.actor_a, scope.actor_b):
        response = request(scope, actor, "GET", path)
        assert_status(response, 404)
        assert scope.title_a not in response.text and "fixture-private-trajectory-body" not in response.text
    snapshot = request(scope, scope.actor_b, "GET", path + "/snapshot", params={"trajectory_id": run_id})
    assert_status(snapshot, 404)
    with pytest.raises(PermissionError):
        add_run(scope, scope.identity_a)

    assert (
        archive.read_bytes() == archive_before
        and (archive.parent / "meta.json").read_bytes() == manifest_before
    )
    with get_db_session() as session:
        session.query(UserTenant).filter_by(user_id=scope.identity_a.owner_user_id).one().tenant_id = "tenant-a"
    assert_status(request(scope, scope.actor_a, "GET", path), 200)


def test_pg_manual_cleanup_is_restricted_to_the_authorized_tenant(pg_scope):
    scope = pg_scope
    _, retained = add_run(scope, scope.identity_a, age_days=8)
    _, selected = add_run(scope, scope.identity_b, age_days=8)
    original = retained.read_bytes()
    path = "/trajectory/cleanup"
    assert_status(request(scope, scope.owner_a, "POST", path, json={"before_days": 7}), 403)
    assert_status(
        request(scope, scope.actor_a, "POST", path, json={"before_days": 7, "tenant_id": "tenant-b"}), 404
    )
    assert_status(request(scope, scope.superuser, "POST", path, json={"before_days": 7}), 422)
    assert selected.exists()
    outcome = request(scope, scope.superuser, "POST", path, json={"before_days": 7, "tenant_id": "tenant-b"})
    assert_status(outcome, 200)
    assert outcome.json()["data"]["deleted_runs"] == 1 and not selected.exists()
    assert retained.read_bytes() == original
