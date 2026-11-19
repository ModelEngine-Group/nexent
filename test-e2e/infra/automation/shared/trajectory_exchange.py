# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned native files and HTTP applications; only the identity/PG boundary is controlled."""

import asyncio
import io
import json
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.trace.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from nexent.core.concurrency import LanePolicy, ThreadManager
from ops.api import trajectory as api
from ops.services.trajectory.primitives import QueryError, ReferenceStore
from ops.services.trajectory.service import TrajectoryService

BODY = (
    '归档正文😀\\\n"<img src="https://invalid.example/never" onerror="window.archiveExecuted=true">'
    * 1000
)


class Catalog:
    def __init__(self):
        self.revoked = False
        self.calls = 0

    def tenants(self, actor):
        return [actor.tenant_id]

    def actor_active(self, actor):
        return not self.revoked

    def resolve(self, tenants, conversation_id, target_user_id=None):
        self.calls += 1
        if (
            self.revoked
            or tenants != ["source"]
            or conversation_id != "123"
            or target_user_id not in (None, "owner")
        ):
            raise QueryError("trajectory_not_found", 404)
        return {
            "tenant_id": "source",
            "user_id": "owner",
            "user_name": "Owner",
            "agent_id": "7",
            "conversation_id": "123",
            "conversation_title": "Archive fixture",
        }

    def builtin_agent_ids(self, *args):
        return set()

    def message_upper(self, *args):
        return 0


def seed(root, count=3, name_prefix="Archive"):
    catalog = Catalog()
    store = TrajectoryFileStore(
        root,
        authorize=lambda owner: catalog.resolve(
            [owner.tenant_id], owner.conversation_id, owner.owner_user_id
        ),
    )
    owner = CaptureIdentity("source", "owner", "123", "7")
    runs = []
    for index in range(count):
        run_id = str(uuid4())
        spans = []
        for number, kind in enumerate(("AGENT", "LLM", "TOOL"), 1):
            attrs = {
                "tenant.id": "source",
                "nexent.owner_user_id": "owner",
                "conversation.id": "123",
                "session.id": "123",
                "nexent.trace_id": "123",
                "nexent.trajectory_id": run_id,
                "nexent.record_id": f"node-{number}",
                "openinference.span.kind": kind,
                "input.value": f"input-{index}",
                "output.value": BODY if number == 3 else "answer",
            }
            if number != 1:
                attrs["nexent.parent_record_id"] = "node-1"
            else:
                attrs.update(
                    {
                        "agent.id": "7",
                        "agent.version_no": index,
                        "agent.version_name": f"Version {index}",
                    }
                )
            if number == 2:
                attrs.update(
                    {
                        "llm.model_name": "fixture-model",
                        "llm.token_count.prompt": 4,
                        "llm.token_count.completion": 6,
                        "nexent.reasoning.value": "reasoning 😀",
                        "nexent.raw.value": '{"original":null}',
                    }
                )
            spans.append(
                {
                    "traceId": "a" * 32,
                    "spanId": f"{number:016x}",
                    "name": f"{name_prefix} {index}" if number == 1 else kind,
                    "startTimeUnixNano": "1000000000",
                    "endTimeUnixNano": "2000000000",
                    "attributes": [
                        {
                            "key": key,
                            "value": {"intValue": str(value)}
                            if type(value) is int
                            else {"stringValue": value},
                        }
                        for key, value in attrs.items()
                    ],
                }
            )
        with store.start(owner, run_id, str(uuid4()), core_type="smolagents") as writer:
            writer.append(
                [{"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}],
                batch_id=str(uuid4()),
                expected_offset=0,
            )
            writer.finish("completed")
        runs.append(run_id)
    return SimpleNamespace(
        store=store,
        owner=owner,
        catalog=catalog,
        runs=runs,
        service=TrajectoryService(store, catalog, ReferenceStore()),
    )


@contextmanager
def http_app(monkeypatch, source=None):
    manager = ThreadManager(
        "archive-case", {"trajectory-read": LanePolicy("trajectory-read", 2, 2)}
    )
    manager.start()
    app = FastAPI()
    app.state.thread_manager = manager
    app.include_router(api.router)

    def context(header):
        if not header:
            return None, None, ()
        if header == "user":
            return "user", "local", ("USER",)
        return "admin", "other" if header == "other" else "source", ("OPS",)

    def get_service():
        if source is None:
            raise AssertionError(
                "Import must not initialize a capture service or source database"
            )
        return source.service

    with monkeypatch.context() as patch:
        patch.setattr(api, "get_current_user_context", context)
        patch.setattr(api, "get_service", get_service)
        try:
            with TestClient(app) as client:
                yield SimpleNamespace(client=client, manager=manager, app=app)
        finally:
            asyncio.run(manager.shutdown(timeout=3))
            assert manager.snapshot().active_count == 0


def exported(http):
    result = http.client.post(
        "/trajectory/conversations/123/export", headers={"Authorization": "admin"}
    )
    assert result.status_code == 200, result.text
    return result


def imported(http, content, actor="admin"):
    return http.client.post(
        "/trajectory/import",
        files={"file": ("trajectory.zip", content, "application/zip")},
        headers={"Authorization": actor} if actor else {},
    )


def rewrite(raw, edit):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = {item.filename: archive.read(item) for item in archive.infolist()}
    edit(entries)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def change_meta(entries, change):
    name = next(name for name in entries if name.endswith("meta.json"))
    meta = json.loads(entries[name])
    change(meta)
    entries[name] = json.dumps(meta).encode()
