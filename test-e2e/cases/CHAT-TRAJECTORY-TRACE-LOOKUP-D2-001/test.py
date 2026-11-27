# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify trajectory lookup and message references against committed PostgreSQL rows."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.schema import CreateSchema

from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.client import db_client, get_db_session
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from infrastructure.rdb.trajectory.capture import CaptureCatalog
from infrastructure.trace.trajectory_store import CaptureIdentity, TrajectoryFileStore
from management.db.agent.models import AgentInfo
from nexent.core.concurrency import LanePolicy, ThreadManager
from ops.api import trajectory as api
from ops.db.trajectory.catalog import TrajectoryCatalog
from ops.services.trajectory.primitives import ReferenceStore
from ops.services.trajectory.service import TrajectoryService
from shared.factories.scratch_database import isolated_product_database

pytestmark = [pytest.mark.case_id("CHAT-TRAJECTORY-TRACE-LOOKUP-D2-001"), pytest.mark.stage("D2")]

USERS = {
    "owner": ("tenant-a", ("USER",)),
    "ops": ("tenant-a", ("OPS",)),
    "dev": ("tenant-a", ("DEV",)),
    "other": ("tenant-b", ("OPS",)),
    "su": ("tenant-b", ("SU",)),
}


def add_conversation(owner="owner", agent=101):
    with get_db_session() as session:
        record = ConversationRecord(created_by=owner, agent_id=agent, conversation_title=f"Fixture {owner}")
        session.add(record)
        session.flush()
        return str(record.conversation_id)


def add_message(conversation, content):
    with get_db_session() as session:
        message = ConversationMessage(conversation_id=int(conversation), message_role="user", message_content=content)
        session.add(message)
        session.flush()
        return str(message.message_id)


def update_row(model, row_id, **values):
    with get_db_session() as session:
        row = session.get(model, int(row_id))
        for name, value in values.items():
            setattr(row, name, value)


@pytest.fixture
def lookup(tmp_path, monkeypatch):
    with isolated_product_database(), TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        models = (AgentInfo, UserAccount, UserTenant, ConversationRecord, ConversationMessage)
        tables = [model.__table__ for model in models]
        with db_client.engine.begin() as connection:
            connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
            TableBase.metadata.create_all(connection, tables=tables)
        with get_db_session() as session:
            for user, (tenant, roles) in USERS.items():
                session.add(UserAccount(user_id=user, user_roles=list(roles)))
                session.add(UserTenant(user_id=user, tenant_id=tenant))

        now = [datetime.now(UTC)]
        capture = CaptureCatalog()

        def sources(identity, upper):
            return capture.source_messages(
                identity.tenant_id, identity.owner_user_id, identity.conversation_id, upper=upper
            )

        catalog = TrajectoryCatalog()
        store = TrajectoryFileStore(root, authorize=capture.authorize, source_query=sources, clock=lambda: now[0])
        service = TrajectoryService(store, catalog, ReferenceStore(), source_query=sources)
        manager = ThreadManager("trajectory-lookup-pg", {"trajectory-read": LanePolicy("trajectory-read", 2, 2)})
        app = FastAPI()
        app.include_router(api.router)
        app.state.thread_manager = manager

        def identity(header):
            tenant, roles = USERS.get(header, (None, ()))
            return header if tenant else None, tenant, roles

        monkeypatch.setattr(api, "get_current_user_context", identity)
        monkeypatch.setattr(api, "get_service", lambda: service)
        manager.start()
        try:
            with TestClient(app) as client:
                yield SimpleNamespace(client=client, store=store, root=root, now=now)
        finally:
            asyncio.run(manager.shutdown(timeout=5))
            assert manager.state.value == "closed"


def archive_run(lookup, conversation, message, *, agent="101", gap=False):
    identity = CaptureIdentity("tenant-a", "owner", conversation, agent)
    run, root, child, nested, sibling = (str(uuid4()) for _ in range(5))
    trace_id = uuid4().hex
    start = lookup.now[0] - timedelta(seconds=2)
    start_ns = int(start.timestamp() * 1e9)
    spans = []
    for index, (node, parent, kind) in enumerate(
        ((root, None, "AGENT"), (child, 1, "AGENT"), (nested, 2, "LLM"), (sibling, 1, "LLM")), start=1
    ):
        values = {
            "tenant.id": identity.tenant_id,
            "nexent.owner_user_id": identity.owner_user_id,
            "conversation.id": conversation,
            "session.id": conversation,
            "nexent.trace_id": conversation,
            "nexent.trajectory_id": run,
            "nexent.record_id": node,
            "openinference.span.kind": kind,
            "output.value": "fixture answer" if node == root else "child result",
        }
        span = {
            "traceId": trace_id,
            "spanId": f"{index:016x}",
            "name": "Fixture Agent" if kind == "AGENT" else "Fixture model",
            "startTimeUnixNano": str(start_ns),
            "endTimeUnixNano": str(start_ns + 1_000_000_000),
            "kind": 1,
            "status": {"code": 1},
        }
        if parent is not None:
            span["parentSpanId"] = f"{parent:016x}"
            values["nexent.parent_record_id"] = (root, child)[parent - 1]
        span["attributes"] = [{"key": key, "value": {"stringValue": value}} for key, value in values.items()]
        spans.append(span)
    request = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
    with lookup.store.start(identity, run, str(uuid4()), core_type="smolagents", started_at=start,
                            source_message_id=message) as writer:
        writer.append([request], batch_id=str(uuid4()), expected_offset=0)
        if gap:
            writer.mark_incomplete("queue_full")
        writer.finish("completed", finished_at=lookup.now[0])
    return SimpleNamespace(id=run, identity=identity, parents={root: None, child: root, nested: child, sibling: root})


def get(lookup, conversation, suffix="", *, actor="ops", **params):
    response = lookup.client.get(f"/trajectory/conversations/{conversation}{suffix}",
                                 headers={"Authorization": actor}, params=params)
    assert response.headers["cache-control"] == "private,no-store"
    return response


def data(response):
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    return response.json()["data"]


def test_trace_lookup_keeps_pg_identity_and_first_archive_directory(lookup):
    conversation = add_conversation()
    first = archive_run(lookup, conversation, add_message(conversation, "first"))
    update_row(ConversationRecord, conversation, agent_id=202)
    following = [archive_run(lookup, conversation, add_message(conversation, f"turn {turn}"), agent="202")
                 for turn in (2, 3)]
    page = data(get(lookup, conversation, limit=1, actor="su", tenant_id="tenant-a"))
    executions = list(page["executions"])
    while page["next_cursor"]:
        page = data(get(lookup, conversation, limit=1, cursor=page["next_cursor"], actor="su", tenant_id="tenant-a"))
        executions.extend(page["executions"])
    assert page["trace_id"] == page["conversation_id"] == conversation
    assert [(row["round_no"], row["trajectory_id"]) for row in executions] == [
        (index, recorded.id) for index, recorded in enumerate([first, *following], start=1)
    ]
    assert [row["root_agent_id"] for row in executions] == ["101", "202", "202"]
    assert (lookup.root / "tenant-a" / "owner" / "101" / conversation / "meta.json").is_file()
    assert not (lookup.root / "tenant-a" / "owner" / "202" / conversation).exists()
    nodes = data(get(lookup, conversation, "/snapshot", trajectory_id=first.id))["nodes"]
    assert {node["id"]: node["parent_id"] for node in nodes} == first.parents
    assert sum(node["kind"] == "model" for node in nodes) == 2

    unknown = add_conversation(agent=None)
    no_agent = archive_run(lookup, unknown, add_message(unknown, "without a root agent"), agent=None)
    assert data(get(lookup, unknown))["executions"][0]["trajectory_id"] == no_agent.id
    assert (lookup.root / "tenant-a" / "owner" / "_unknown" / unknown / "meta.json").is_file()


def test_trace_lookup_missing_archive_is_distinct_from_exhausted_lookup(lookup):
    conversation = add_conversation()
    missing = data(get(lookup, conversation))
    assert missing["trace_id"] == conversation
    assert missing["availability"] == "not_captured" and not missing["executions"]
    assert not (lookup.root / "tenant-a" / "owner").exists()
    other_owner = lookup.root / "tenant-a" / "unrelated-owner"
    other_owner.mkdir(parents=True)
    owner = lookup.root / "tenant-a" / "owner"
    owner.mkdir()
    for candidate in range(1, 4098):
        (owner / str(candidate)).mkdir()
    exhausted = get(lookup, conversation)
    assert exhausted.status_code == 503 and exhausted.headers["retry-after"] == "2"
    assert exhausted.json() == {"detail": {"code": "lookup_unavailable"}}
    assert list(other_owner.iterdir()) == []
    assert len(list(owner.iterdir())) == 4097


def test_trace_lookup_pg_message_cursor_and_content_version(lookup):
    conversation = add_conversation()
    body = "第一条😀\n" * 1500
    original = [add_message(conversation, text) for text in (body, "second", "third")]
    assert "messages" not in data(get(lookup, conversation))
    page = data(get(lookup, conversation, include="messages", limit=1))
    reference = "/contents/" + page["messages"][0]["content_id"]
    assert not page["messages"][0]["complete"]
    assert page["coverage"]["chat"]["has_more"] and page["coverage"]["chat"]["complete"]
    add_message(conversation, "arrived after the snapshot")
    update_row(ConversationMessage, original[1], message_content="second edited before reading")
    seen = [page["messages"][0]]
    while page["message_cursor"]:
        page = data(get(lookup, conversation, include="messages", limit=1, message_cursor=page["message_cursor"]))
        assert page["coverage"]["chat"]["message_id_upper"] == original[-1]
        seen.extend(page["messages"])
    assert [message["message_id"] for message in seen] == original
    assert seen[1]["preview"] == "second edited before reading"
    assert page["coverage"]["chat"]["has_more"] is False
    offset, chunks = 0, []
    while offset < len(body.encode()):
        part = data(get(lookup, conversation, reference, offset=offset, limit=2048))
        assert 0 < len(part["text"].encode()) <= 2048
        chunks.append(part["text"])
        assert part["next_offset"] == offset + len(part["text"].encode())
        offset = part["next_offset"]
    assert "".join(chunks) == body
    for values in ({"message_content": "changed"}, {"delete_flag": "Y"}):
        update_row(ConversationMessage, original[0], **values)
        response = get(lookup, conversation, reference)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "snapshot_reset"
    assert get(lookup, conversation, limit=201).status_code == 422
    assert get(lookup, conversation, reference, limit=1048577).status_code == 422


def test_trace_lookup_retention_reports_separate_archive_and_chat_coverage(lookup):
    conversation = add_conversation()
    first = archive_run(lookup, conversation, add_message(conversation, "first"))
    full = data(get(lookup, conversation, include="messages"))["coverage"]
    assert full["chat"]["complete"] and full["conversation"]["complete"]
    initial = data(get(lookup, conversation, "/snapshot", trajectory_id=first.id))
    root = next(node for node in initial["nodes"] if node["parent_id"] is None)
    archive_body = "/contents/" + root["output"]["content_id"]
    assert data(get(lookup, conversation, archive_body))["text"] == "fixture answer"
    lookup.now[0] += timedelta(days=31)
    message = add_message(conversation, "fresh")
    archive_run(lookup, conversation, message)
    view = data(get(lookup, conversation, include="messages", limit=1))
    assert view["availability"] == "available"
    assert view["coverage"]["chat"]["complete"] and view["coverage"]["chat"]["has_more"]
    assert view["coverage"]["retention_window"]["complete"]
    assert view["coverage"]["retention_window"]["execution_count"] == 1
    assert "expired" in view["coverage"]["conversation"]["reasons"]
    assert get(lookup, conversation, archive_body).status_code == 410
    lookup.now[0] += timedelta(days=31)
    expired = data(get(lookup, conversation, include="messages"))
    assert expired["trace_id"] == conversation and expired["availability"] == "expired"
    assert [row["preview"] for row in expired["messages"]] == ["first", "fresh"]


@pytest.mark.parametrize(("late_start", "reason"), [(True, "has_uncaptured_history"), (False, "had_capture_gap")])
def test_trace_lookup_pg_history_keeps_incomplete_capture_visible(lookup, late_start, reason):
    conversation = add_conversation()
    if late_start:
        add_message(conversation, "before capture was enabled")
    recorded = archive_run(lookup, conversation, add_message(conversation, "capture input"), gap=not late_start)
    view = data(get(lookup, conversation, include="messages"))
    assert view["executions"][0]["trajectory_id"] == recorded.id
    assert view["coverage"]["chat"]["complete"] and not view["coverage"]["chat"]["has_more"]
    assert not view["coverage"]["conversation"]["complete"]
    assert reason in view["coverage"]["conversation"]["reasons"]


def test_trace_lookup_rechecks_committed_owner_and_preserves_other_conversations(lookup):
    own = add_conversation()
    canary = add_conversation(owner="other")
    canary_message = add_message(canary, "other tenant canary")
    own_message = add_message(own, "owned history")
    view = data(get(lookup, own, include="messages"))
    reference = "/contents/" + view["messages"][0]["content_id"]
    missing = get(lookup, "2147483647")
    for suffix in ("", "/snapshot"):
        params = {"trajectory_id": str(uuid4())} if suffix == "/snapshot" else {}
        denied = get(lookup, own, suffix, actor="other", **params)
        assert denied.status_code == missing.status_code == 404 and denied.json() == missing.json()
        for actor in ("owner", "dev"):
            assert get(lookup, own, suffix, actor=actor, **params).status_code == 403
    wrong_actor = get(lookup, own, reference, actor="other")
    assert wrong_actor.status_code == 422
    assert wrong_actor.json() == get(lookup, own, reference + "x").json()
    for actor in ("owner", "dev"):
        assert get(lookup, own, reference, actor=actor).status_code == 403
    assert get(lookup, canary, reference).status_code == 404
    for invalid in ("0", "01", "-1", "2147483648"):
        assert get(lookup, invalid).status_code == 422
    assert get(lookup, own, cursor="invalid").status_code == 422
    assert data(get(lookup, own, reference))["text"] == "owned history"
    update_row(ConversationRecord, own, delete_flag="Y")
    assert get(lookup, own, reference).status_code == 404
    with get_db_session() as session:
        assert session.get(ConversationMessage, int(own_message)).message_content == "owned history"
        assert session.get(ConversationMessage, int(canary_message)).message_content == "other tenant canary"
