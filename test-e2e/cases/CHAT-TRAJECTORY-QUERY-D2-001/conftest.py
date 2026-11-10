# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private HTTP/file fixtures with controlled PG authorization boundaries."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from management.api.observability import trajectory as api
from management.services.trajectory.primitives import QueryError, TokenSigner
from management.services.trajectory.service import TrajectoryService
from nexent.core.concurrency import LanePolicy, ThreadManager


class Catalog:
    def __init__(self):
        self.rows, self.chat = {}, {}
        self.members = {("t1", "u1"), ("t2", "u2")}
        self.actors = {
            "admin": ("t1", "ADMIN"),
            "admin2": ("t2", "ADMIN"),
            "su": ("t1", "SU"),
        }

    def tenants(self, actor):
        return ["t1", "t2"] if actor.role == "SU" else [actor.tenant_id]

    def actor_active(self, actor):
        return self.actors.get(actor.user_id) == (actor.tenant_id, actor.role)

    def user_active(self, tenant_id, user_id):
        return (tenant_id, user_id) in self.members

    def candidates(
        self, tenants, *, target_user_id=None, conversation_id=None, limit=10000
    ):
        result = [
            dict(r)
            for r in self.rows.values()
            if r["tenant_id"] in tenants
            and (r["tenant_id"], r["user_id"]) in self.members
            and (not target_user_id or r["user_id"] == target_user_id)
            and (not conversation_id or r["conversation_id"] == conversation_id)
        ]
        if len(result) > limit:
            raise QueryError("candidate_budget_exceeded", 503)
        return sorted(result, key=lambda r: int(r["conversation_id"]))

    def resolve(self, tenants, conversation_id, *, target_user_id=None):
        rows = self.candidates(
            tenants, target_user_id=target_user_id, conversation_id=conversation_id
        )
        if len(rows) != 1:
            raise QueryError("trajectory_not_found", 404)
        return rows[0]

    def cleanup_candidates(self, tenant_id, after, *, limit):
        return [
            r
            for r in self.candidates([tenant_id])
            if int(r["conversation_id"]) >= after
        ][:limit]

    def names(self, tenants):
        return {t: "Tenant " + t for t in tenants}

    def users(self, tenants, *, limit):
        return [
            {"id": user, "name": user, "tenant_id": tenant}
            for tenant, user in sorted(self.members)
            if tenant in tenants
        ]

    def user_page(self, tenants, search, after, limit):
        return [
            option
            for option in self.users(tenants, limit=limit)
            if (not search or search in option["name"])
            and (not after or (option["tenant_id"], option["id"]) > tuple(after))
        ][: limit + 1]

    def agent_names(self, tenants, ids):
        return {
            (tenant, agent): "Agent " + agent for tenant in tenants for agent in ids
        }

    def directory_page(
        self, tenant_id, user_id, category, group_key, after, limit, search
    ):
        rows = [
            r
            for r in self.candidates([tenant_id], target_user_id=user_id)
            if r["category"] == category
        ]
        if group_key:
            rows = [
                r
                for r in rows
                if ("agent:" + r["agent_id"] if r["agent_id"] else "other") == group_key
            ]
            result = {int(r["conversation_id"]): r for r in rows}
        else:
            result = {int(r["agent_id"]) if r["agent_id"] else 0: r for r in rows}
        return [result[key] for key in sorted(result) if key > after][: limit + 1]

    def message_upper(self, conversation_id):
        return max(self.chat.get(conversation_id, {0: ""}))

    def messages(self, conversation_id, upper, after, limit):
        return [
            {
                "message_id": str(key),
                "role": "user",
                "preview": value[:4096],
                "char_count": len(value),
                "byte_count": len(value.encode()),
                "hash": hashlib.md5(value.encode()).hexdigest(),
                "status": "completed",
            }
            for key, value in sorted(self.chat.get(conversation_id, {}).items())
            if int(after) < key <= upper
        ][: limit + 1]

    def message_content(self, conversation_id, message_id, offset, count):
        text = self.chat.get(conversation_id, {}).get(int(message_id))
        if text is None:
            return None
        return (
            text.encode()[offset : offset + count],
            hashlib.md5(text.encode()).hexdigest(),
            len(text),
            len(text.encode()),
        )


@pytest.fixture
def harness(tmp_path, monkeypatch):
    now = [datetime.now(UTC)]
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    catalog = Catalog()

    def authorize(identity):
        catalog.resolve(
            [identity.tenant_id],
            identity.conversation_id,
            target_user_id=identity.owner_user_id,
        )

    store = TrajectoryFileStore(
        tmp_path, root_id, authorize=authorize, clock=lambda: now[0]
    )
    service = TrajectoryService(store, catalog, TokenSigner("query-test-key-" * 4))
    manager = ThreadManager(
        "trajectory-http-fixture",
        {
            "trajectory-read": LanePolicy("trajectory-read", 2, 2),
            "trajectory-cleanup": LanePolicy("trajectory-cleanup", 1, 0),
        },
    )
    manager.start()
    app = FastAPI()
    app.state.thread_manager = manager
    app.include_router(api.router)
    from management.api.conversation import conversation_management as conversations
    from management.api.identity import user as users_api

    app.include_router(conversations.router)
    app.include_router(users_api.router)

    def context(header):
        if not header:
            from contracts.errors.exceptions import TokenExpiredError

            raise TokenExpiredError("Missing session")
        if header == "user":
            return "u1", "t1", "USER"
        tenant, role = catalog.actors.get(header, ("t1", "ADMIN"))
        return header, tenant, role

    monkeypatch.setattr(api, "get_current_user_context", context)
    monkeypatch.setattr(api, "get_service", lambda: service)
    monkeypatch.setattr(
        conversations, "get_current_user_id", lambda header: context(header)[:2]
    )
    monkeypatch.setattr(users_api, "get_current_user_context", context)
    monkeypatch.setattr(
        users_api, "extract_session_id_from_authorization", lambda _: None
    )
    monkeypatch.setattr(
        users_api,
        "get_users_for_requester",
        lambda *args, **kwargs: {"users": [{"user_id": "u1"}], "total": 1},
    )
    monkeypatch.setattr(
        conversations,
        "list_agent_groups",
        lambda *args: {
            "items": [],
            "included": [{"group_key": "agent:7"}],
            "next_cursor": None,
        },
    )
    monkeypatch.setattr(
        conversations,
        "list_agent_group_conversations",
        lambda *args: {"items": [], "next_cursor": None},
    )

    state = SimpleNamespace(
        store=store,
        catalog=catalog,
        service=service,
        root=tmp_path,
        now=now,
        app=app,
        root_id=root_id,
    )

    def add_conversation(
        conversation="123", tenant="t1", owner="u1", agent="7", category="agent_chat"
    ):
        row = {
            "conversation_id": conversation,
            "conversation_title": "Conversation " + conversation,
            "tenant_id": tenant,
            "user_id": owner,
            "user_name": owner,
            "agent_id": agent,
            "category": category,
        }
        catalog.rows[conversation] = row
        return row

    def add_run(
        conversation="123",
        agent="7",
        status="completed",
        duration=1000,
        ttft=25,
        body="工具结果\n",
        age_days=0,
        model="model-a",
        fragment=False,
        missing_usage=False,
        legacy=False,
    ):
        row = catalog.rows[conversation]
        identity = CaptureIdentity(
            row["tenant_id"], row["user_id"], conversation, agent
        )
        run, root, sub, model1, model2, tool = (str(uuid4()) for _ in range(6))
        begin = now[0] - timedelta(days=age_days, seconds=2)
        base = int(begin.timestamp() * 1e9)
        spans = []
        for index, (record, parent, kind) in enumerate(
            [
                (root, None, "AGENT"),
                (sub, root, "AGENT"),
                (model1, sub, "LLM"),
                (model2, root, "LLM"),
                (tool, root, "TOOL"),
            ]
        ):
            attrs = {
                "tenant.id": identity.tenant_id,
                "nexent.owner_user_id": identity.owner_user_id,
                "conversation.id": conversation,
                "session.id": conversation,
                "nexent.trace_id": conversation,
                "nexent.trajectory_id": run,
                "nexent.record_id": record,
                "openinference.span.kind": kind,
                "input.value": '输入\n"\\',
                "output.value": body if kind == "TOOL" else "回答",
            }
            if parent:
                attrs["nexent.parent_record_id"] = parent
            if kind == "LLM":
                attrs.update(
                    {
                        "llm.model_name": model,
                        "llm.token_count.prompt": 20,
                        "llm.token_count.completion": 5,
                        "llm.ttft_ms": ttft,
                        "nexent.reasoning.value": "真实返回的思考",
                    }
                )
            spans.append(
                {
                    "traceId": "a" * 32,
                    "spanId": f"{index + 1:016x}",
                    "name": "Agent Demo" if kind == "AGENT" else kind,
                    "startTimeUnixNano": str(base),
                    "endTimeUnixNano": str(base + duration * 1000000),
                    "kind": 1,
                    "status": {"code": 1 if status == "completed" else 2},
                    "attributes": [
                        {
                            "key": k,
                            "value": {"intValue": str(v)}
                            if type(v) is int
                            else {"stringValue": v},
                        }
                        for k, v in attrs.items()
                    ],
                }
            )
        if legacy:
            for item in spans:
                item["attributes"] = [
                    a
                    for a in item["attributes"]
                    if a["key"]
                    not in (
                        "nexent.record_id",
                        "nexent.parent_record_id",
                        "nexent.reasoning.value",
                    )
                ]
                if item["spanId"] != "0000000000000001":
                    item["parentSpanId"] = "0000000000000001"
        if missing_usage:
            spans[2]["attributes"] = [
                a
                for a in spans[2]["attributes"]
                if not a["key"].startswith("llm.token_count")
            ]
        if fragment:
            attrs = {
                a["key"]: next(iter(a["value"].values()))
                for a in spans[2]["attributes"]
            }
            attrs["nexent.owner_span_id"] = spans[2]["spanId"]
            attrs["nexent.span.role"] = "fragment"
            spans.append(
                {
                    **spans[2],
                    "spanId": "0000000000000006",
                    "parentSpanId": spans[2]["spanId"],
                    "name": "nexent.trajectory.fragment",
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in attrs.items()
                    ],
                    "events": [
                        {
                            "name": "nexent.trajectory.snapshot",
                            "attributes": [
                                {
                                    "key": "nexent.event_id",
                                    "value": {"stringValue": str(uuid4())},
                                },
                                {
                                    "key": "nexent.snapshot_mode",
                                    "value": {"stringValue": "replace"},
                                },
                                {
                                    "key": "output.value",
                                    "value": {"stringValue": "旧片段"},
                                },
                            ],
                        }
                    ],
                }
            )
        request = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
        with store.start(
            identity, run, str(uuid4()), core_type="smolagents", started_at=begin
        ) as writer:
            writer.append([request], batch_id=str(uuid4()), expected_offset=0)
            writer.finish(status, finished_at=begin + timedelta(milliseconds=duration))
        return SimpleNamespace(
            id=run,
            identity=identity,
            root=root,
            sub=sub,
            model1=model1,
            model2=model2,
            tool=tool,
        )

    state.add_conversation, state.add_run = add_conversation, add_run
    add_conversation()
    state.run = add_run()
    try:
        with TestClient(app) as client:
            state.client = client
            yield state
    finally:
        asyncio.run(manager.shutdown(timeout=3))
        assert manager.snapshot().active_count == 0
