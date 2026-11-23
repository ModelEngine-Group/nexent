# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real router and PostgreSQL coverage for two-level Agent history paging."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import importlib.machinery
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import null
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema


# Keep product service initialization inside the controlled test boundary.
boto3_module = ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules.setdefault("boto3", boto3_module)
patch("botocore.client.BaseClient._make_api_call", return_value={}).start()
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch(
    "nexent.storage.storage_client_factory.create_storage_client_from_config",
    return_value=storage_client_mock,
).start()
patch(
    "nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None
).start()
patch("backend.database.client.MinioClient", return_value=minio_mock).start()
patch("database.client.MinioClient", return_value=minio_mock).start()
patch("backend.database.client.minio_client", minio_mock).start()
patch("elasticsearch.Elasticsearch", return_value=MagicMock()).start()

from apps import conversation_management_app as routes
from database import conversation_agent_history_db
from database.client import db_client
from database.db_models import AgentInfo, ConversationRecord


@pytest.fixture
def history_app(monkeypatch, request):
    schema = "chat_hist_" + uuid4().hex
    engine = db_client.engine.execution_options(schema_translate_map={"nexent": schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))

    def drop_schema():
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))

    request.addfinalizer(drop_schema)
    with engine.begin() as connection:
        ConversationRecord.__table__.create(connection)
        AgentInfo.__table__.create(connection)

    base = datetime(2026, 1, 1)
    with Session(engine) as session, session.begin():
        for agent_id in range(7, 19):
            session.add(
                AgentInfo(
                    agent_id=agent_id,
                    version_no=0,
                    name=f"Agent {agent_id}",
                    display_name=f"Agent {agent_id}",
                    tenant_id="tenant",
                    enabled=True,
                    current_version_no=1,
                    delete_flag="N",
                )
            )
        for identity in range(1, 102):
            activity = base + timedelta(minutes=identity)
            session.add(
                ConversationRecord(
                    conversation_id=identity,
                    conversation_title=f"Agent Seven Session {identity:03d}",
                    created_by="owner",
                    updated_by="owner",
                    agent_id=7,
                    workbench_config=null(),
                    workbench_pinned_at=base + timedelta(days=2)
                    if identity == 1
                    else None,
                    create_time=activity,
                    update_time=activity,
                    last_activity_time=activity,
                    delete_flag="N",
                )
            )
        for agent_id in range(8, 19):
            identity = 1_000 + agent_id
            activity = base + timedelta(days=1, minutes=agent_id)
            session.add(
                ConversationRecord(
                    conversation_id=identity,
                    conversation_title=f"Agent {agent_id} Session",
                    created_by="owner",
                    updated_by="owner",
                    agent_id=agent_id,
                    workbench_config=null(),
                    create_time=activity,
                    update_time=activity,
                    last_activity_time=activity,
                    delete_flag="N",
                )
            )
        session.add_all(
            [
                ConversationRecord(
                    conversation_id=2_001,
                    conversation_title="Foreign history",
                    created_by="other",
                    updated_by="other",
                    agent_id=7,
                    workbench_config=null(),
                    create_time=base,
                    update_time=base,
                    last_activity_time=base,
                    delete_flag="N",
                ),
                ConversationRecord(
                    conversation_id=2_002,
                    conversation_title="Deleted history",
                    created_by="owner",
                    updated_by="owner",
                    agent_id=7,
                    workbench_config=null(),
                    create_time=base,
                    update_time=base,
                    last_activity_time=base,
                    delete_flag="Y",
                ),
                ConversationRecord(
                    conversation_id=2_003,
                    conversation_title="Workbench history",
                    created_by="owner",
                    updated_by="owner",
                    agent_id=7,
                    workbench_config={},
                    create_time=base,
                    update_time=base,
                    last_activity_time=base,
                    delete_flag="N",
                ),
            ]
        )

    @contextmanager
    def sessions():
        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(conversation_agent_history_db, "get_db_session", sessions)
    identities = {
        "Bearer owner": ("owner", "tenant"),
        "Bearer other": ("other", "tenant"),
    }
    monkeypatch.setattr(
        routes, "get_current_user_id", lambda token: identities.get(token, (None, None))
    )
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    yield engine, app


@pytest.mark.case_id("CHAT-SIDEBAR-D3-002")
@pytest.mark.stage("D3")
def test_authenticated_agent_history_group_and_conversation_paging(history_app):
    _, app = history_app
    owner = TestClient(app, headers={"Authorization": "Bearer owner"})
    other = TestClient(app, headers={"Authorization": "Bearer other"})

    first_groups = owner.get("/api/conversation/agent_groups", params={"limit": 10})
    assert first_groups.status_code == 200, first_groups.text
    first_group_data = first_groups.json()["data"]
    assert len(first_group_data["items"]) == 10, first_groups.text
    assert [group["agent_id"] for group in first_group_data["pinned_items"]] == [7]
    assert all(group["agent_id"] != 7 for group in first_group_data["items"])
    included = owner.get(
        "/api/conversation/agent_groups",
        params={"limit": 10, "include_agent_id": 7},
    )
    assert included.status_code == 200, included.text
    assert [
        group["agent_id"] for group in included.json()["data"]["included_items"]
    ] == [7]

    groups = list(first_group_data["items"])
    cursor = first_group_data["next_cursor"]
    while cursor:
        page = owner.get(
            "/api/conversation/agent_groups", params={"limit": 10, "cursor": cursor}
        )
        assert page.status_code == 200, page.text
        data = page.json()["data"]
        groups.extend(data["items"])
        cursor = data["next_cursor"]
    assert len({group["group_key"] for group in groups}) == 12

    rows = []
    page_cursor = None
    pin_snapshot = None
    while True:
        parameters = {"limit": 10}
        if page_cursor:
            parameters["cursor"] = page_cursor
        response = owner.get(
            "/api/conversation/agent_groups/agent:7/conversations", params=parameters
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        rows.extend(data["items"])
        pin_snapshot = data["pinned_items"]
        page_cursor = data["next_cursor"]
        if page_cursor is None:
            break
    identities = [row["conversation_id"] for row in rows]
    assert len(identities) == 101
    assert len(set(identities)) == 101
    assert identities == sorted(identities, reverse=True)
    assert [item["conversation_id"] for item in pin_snapshot] == [1]
    assert all("message" not in item for item in rows)

    filtered = owner.get(
        "/api/conversation/agent_groups/agent:7/conversations",
        params={"search": "Session 050"},
    )
    assert [item["conversation_id"] for item in filtered.json()["data"]["items"]] == [
        50
    ]
    complete_ids = owner.get("/api/conversation/agent_groups/7/conversation_ids")
    assert complete_ids.status_code == 200, complete_ids.text
    assert len(complete_ids.json()["data"]["items"]) == 101
    assert complete_ids.json()["data"]["items"][0] == 101
    assert 2_001 not in complete_ids.json()["data"]["items"]
    assert 2_002 not in complete_ids.json()["data"]["items"]
    assert 2_003 not in complete_ids.json()["data"]["items"]
    other_groups = other.get("/api/conversation/agent_groups").json()["data"]["items"]
    assert [group["agent_id"] for group in other_groups] == [7]
    other_conversations = other.get(
        "/api/conversation/agent_groups/agent:7/conversations"
    ).json()["data"]["items"]
    assert [item["conversation_title"] for item in other_conversations] == [
        "Foreign history"
    ]

    assert (
        owner.get("/api/conversation/agent_groups/agent:00/conversations").status_code
        == 400
    )
    assert (
        owner.get(
            "/api/conversation/agent_groups/agent:7/conversations",
            params={"cursor": "not-a-valid-cursor"},
        ).status_code
        == 400
    )
    assert (
        owner.get("/api/conversation/agent_groups", params={"limit": 0}).status_code
        == 422
    )
