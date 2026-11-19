# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Snapshot pages preserve ancestors, source bodies and publication bindings."""

import copy
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.trace.trajectory_reader import TrajectoryReadBudgetExceeded
from infrastructure.trace.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from ops.services.trajectory.access import Actor
from ops.services.trajectory.nodes import build_nodes
from ops.services.trajectory.primitives import QueryError, ReferenceStore
from ops.services.trajectory.service import TrajectoryService

ACTOR = Actor("admin", "t", "OPS")
BODY = '中文😀\n"\\' * 2048


@pytest.fixture
def captured(tmp_path):
    store = TrajectoryFileStore(tmp_path / "traces", authorize=lambda _: None)
    owner = CaptureIdentity("t", "u", "1", "7")
    run_id = str(uuid4())
    spans = []
    for index, (name, kind) in enumerate(
        (("root", "AGENT"), ("first", "LLM"), ("second", "LLM"))
    ):
        attrs = {
            "tenant.id": "t",
            "nexent.owner_user_id": "u",
            "conversation.id": "1",
            "session.id": "1",
            "nexent.trace_id": "1",
            "nexent.trajectory_id": run_id,
            "openinference.span.kind": kind,
            "nexent.record_id": name,
            "input.value": "query",
            "output.value": BODY if index == 1 else "answer",
        }
        if index:
            attrs["nexent.parent_record_id"] = "root"
        spans.append(
            {
                "traceId": "a" * 32,
                "spanId": f"{index + 1:016x}",
                "name": name,
                "startTimeUnixNano": str(1_001_000_000 + index * 1_000_000),
                "endTimeUnixNano": "1100000000",
                "attributes": [
                    {"key": k, "value": {"stringValue": v}} for k, v in attrs.items()
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
    catalog = Mock()
    catalog.tenants.return_value = ["t"]
    catalog.actor_active.return_value = True
    catalog.builtin_agent_ids.return_value = set()
    catalog.resolve.return_value = {
        "tenant_id": "t",
        "user_id": "u",
        "user_name": "Owner",
        "conversation_id": "1",
        "conversation_title": "Title",
        "agent_id": "7",
    }
    return TrajectoryService(store, catalog, ReferenceStore()), run_id


def test_pages_return_ancestors_once_and_reuse_parsed_archive(captured, mocker):
    service, run_id = captured
    build = mocker.patch(
        "ops.services.trajectory.service.build_nodes",
        wraps=build_nodes,
    )
    first = service.snapshot(ACTOR, "1", run_id, limit=1)
    assert [n["id"] for n in first["nodes"]] == ["root"]
    assert first["context_nodes"] == [] and not first["scope"]["complete"]
    second = service.snapshot(ACTOR, "1", run_id, cursor=first["next_cursor"], limit=1)
    assert [n["id"] for n in second["nodes"]] == ["first"]
    assert [n["id"] for n in second["context_nodes"]] == ["root"]
    last = service.snapshot(ACTOR, "1", run_id, cursor=second["next_cursor"], limit=1)
    assert [n["id"] for n in last["nodes"]] == ["second"] and last[
        "next_cursor"
    ] is None
    assert build.call_count == 1
    assert first["nodes"][0]["user"] == "Owner"
    assert all(not k.startswith("_") for k in first["nodes"][0])


def test_selected_node_uses_frozen_snapshot_and_content_has_original_bytes(captured):
    service, run_id = captured
    snapshot = service.snapshot(ACTOR, "1", run_id)
    assert snapshot["scope"]["complete"]
    selected = service.snapshot(
        ACTOR,
        "1",
        run_id,
        snapshot_id=snapshot["snapshot_id"],
        node_id="first",
        limit=1,
    )
    body = selected["nodes"][0]["output"]
    assert body["availability"] == "available" and not body["complete"]
    first = service.content(ACTOR, "1", body["content_id"], limit=17)
    second = service.content(
        ACTOR, "1", body["content_id"], offset=first["next_offset"], limit=1024 * 1024
    )
    assert first["text"] + second["text"] == BODY
    assert second["complete"] and second["next_offset"] == len(BODY.encode())
    assert second["offset_unit"] == "utf8_bytes" and second["char_count"] == len(BODY)


@pytest.mark.parametrize("limit", [0, 501])
def test_snapshot_rejects_invalid_page_limit(captured, limit):
    service, run_id = captured
    with pytest.raises(QueryError, match="invalid_limit"):
        service.snapshot(ACTOR, "1", run_id, limit=limit)


def test_snapshot_reference_cannot_select_another_run_or_missing_node(captured):
    service, run_id = captured
    result = service.snapshot(ACTOR, "1", run_id)
    with pytest.raises(QueryError, match="invalid_reference"):
        service.snapshot(ACTOR, "1", str(uuid4()), snapshot_id=result["snapshot_id"])
    with pytest.raises(QueryError, match="trajectory_not_found"):
        service.snapshot(ACTOR, "1", run_id, node_id="missing")


def test_cleanup_invalidates_issued_snapshot(captured):
    service, run_id = captured
    result = service.snapshot(ACTOR, "1", run_id)
    original = service.archive.manifest
    service.archive.manifest = Mock(
        side_effect=lambda row: {**original(row), "cleanup_version": 1}
    )
    with pytest.raises(QueryError, match="snapshot_reset"):
        service.snapshot(ACTOR, "1", run_id, snapshot_id=result["snapshot_id"])


@pytest.mark.parametrize(
    "failure", [ValueError("bad node"), TrajectoryReadBudgetExceeded("budget")]
)
def test_load_converts_parser_failures_without_caching(captured, mocker, failure):
    service, run_id = captured
    mocker.patch("ops.services.trajectory.service.build_nodes", side_effect=failure)
    code = (
        "query_budget_exceeded"
        if isinstance(failure, TrajectoryReadBudgetExceeded)
        else "trajectory_corrupt"
    )
    with pytest.raises(QueryError, match=code):
        service.snapshot(ACTOR, "1", run_id)
    assert service.summaries.size == 0


def test_single_oversized_node_fails_instead_of_returning_empty_page(captured, mocker):
    service, run_id = captured
    original = service._dto
    mocker.patch.object(
        service,
        "_dto",
        side_effect=lambda *args: {**original(*args), "name": "x" * (8 * 1024 * 1024)},
    )
    with pytest.raises(QueryError, match="node_page_budget_exceeded"):
        service.snapshot(ACTOR, "1", run_id)


@pytest.mark.parametrize(
    "offset,limit", [(-1, 4), (True, 4), (0, True), (0, 3), (0, 1048577)]
)
def test_content_range_is_checked_before_reference_resolution(captured, offset, limit):
    service, _ = captured
    with pytest.raises(QueryError, match="invalid_content_range"):
        service.content(ACTOR, "1", "unknown", offset=offset, limit=limit)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"conversation": "2"}, "trajectory_not_found"),
        ({"field": "secret"}, "invalid_content_source"),
        ({"bytes": 0}, "invalid_content_range"),
        ({"end": 10**12}, "invalid_content_range"),
    ],
)
def test_content_rejects_invalid_server_reference_coordinates(captured, change, code):
    service, run_id = captured
    result = service.snapshot(ACTOR, "1", run_id)
    body = result["nodes"][0]["input"]
    state = copy.deepcopy(service.references.resolve(body["content_id"], "content"))
    state.update(change)
    token = service.references.issue("content", state)
    with pytest.raises(QueryError, match=code):
        service.content(ACTOR, "1", token, offset=1)


def test_unsupported_body_encoding_is_explicit(captured):
    service, _ = captured
    assert service._body(None, None, None, None, {}, "input", {}) == {
        "availability": "unsupported_encoding",
        "text": None,
        "complete": False,
        "content_id": None,
    }
