# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise actual HTTP routers, opaque references and private OTLP files."""

import json
import os
from datetime import timedelta

import pytest
from infrastructure.observability.trajectory_store import parse_time
from management.services.trajectory.primitives import QueryError

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-QUERY-D2-001"),
    pytest.mark.stage("D2"),
]


def get(harness, path, *, actor="admin", **params):
    response = harness.client.get(
        path, params=params, headers={"Authorization": actor} if actor else {}
    )
    assert response.headers["cache-control"] == "private,no-store"
    return response


def data(response):
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    return response.json()["data"]


def snapshot(harness, **params):
    return data(
        get(
            harness,
            "/trajectory/conversations/123/snapshot",
            trajectory_id=harness.run.id,
            **params,
        )
    )


def test_trj_query_complete_subtree_and_static_node_paging(harness):
    first = snapshot(harness, limit=1)
    pages, ids = [first], set()
    while True:
        page = pages[-1]
        assert len(page["nodes"]) + len(page["context_nodes"]) <= 500
        for node in page["nodes"]:
            assert node["id"] not in ids
            ids.add(node["id"])
        if not page["next_cursor"]:
            break
        pages.append(snapshot(harness, cursor=page["next_cursor"], limit=1))
    assert len(ids) == 5
    root = next(
        n for page in pages for n in page["nodes"] if n["id"] == harness.run.root
    )
    assert root["display_trace_id"] == "123"
    assert root["user"] == root["user_id"] == "u1"
    assert (
        root["usage"]["total"] == 50 and root["usage"]["scope"] == "execution_subtree"
    )
    assert root["model_call_count"] == 2 and root["tool_call_count"] == 1
    assert root["direct_child_count"] == 3
    models = [n for page in pages for n in page["nodes"] if n["kind"] == "model"]
    assert all(n["ttft_ms"] == 25 and n["throughput"] == 5 for n in models)
    assert all(n["reasoning"]["text"] == "真实返回的思考" for n in models)
    assert all(n["display_trace_id"] == n["id"] for n in models)
    assert all(
        len(n["source"]["trace_id"]) == 32
        and isinstance(n["source"]["export_seq"], str)
        for n in models
    )
    assert (
        get(
            harness,
            "/trajectory/conversations/123/snapshot",
            trajectory_id=harness.run.id,
            cursor=first["next_cursor"] + "x",
        ).status_code
        == 422
    )
    assert (
        get(
            harness,
            "/trajectory/conversations/123/snapshot",
            trajectory_id=harness.run.id,
            limit=501,
        ).status_code
        == 422
    )


def test_trj_query_whole_result_metrics_filters_and_stable_membership(harness):
    second = harness.add_run(
        duration=3000, ttft=0, agent="8", status="failed", model="model-b"
    )
    harness.add_conversation("124", "t2", "u2")
    harness.add_run("124", duration=2000)
    first = data(
        get(
            harness,
            "/trajectory/records",
            actor="su",
            page_size=1,
            sort_by="duration_ms",
            sort_order="asc",
        )
    )
    assert first["total"] == 3 and len(first["items"]) == 1
    assert first["summary"]["conversation_count"] == 2
    assert first["summary"]["duration"]["mean_ms"] == 2000
    assert first["summary"]["duration"]["p90_ms"] == 2800
    assert first["summary"]["ttft"]["sample_count"] == 6
    assert first["summary"]["ttft"]["p50_ms"] == 25
    assert first["items"][0]["duration_ms"] == 1000
    harness.add_run(duration=4000)
    second_page = data(
        get(
            harness,
            "/trajectory/records",
            actor="su",
            page_size=1,
            page=2,
            query_id=first["query_id"],
        )
    )
    assert second_page["total"] == 3
    assert second_page["summary"]["duration"] == first["summary"]["duration"]
    assert data(get(harness, "/trajectory/records", actor="su"))["total"] == 4
    filtered = data(
        get(
            harness,
            "/trajectory/records",
            agent_id="8",
            model="model-b",
            status="error",
            id_query=second.model1,
        )
    )
    assert filtered["total"] == 1 and filtered["items"][0]["trajectory_id"] == second.id
    assert filtered["summary"]["ttft"]["p50_ms"] == 0
    assert (
        data(get(harness, "/trajectory/records", model="absent"))["summary"][
            "duration"
        ]["p50_ms"]
        is None
    )
    assert (
        get(harness, "/trajectory/records", started_from="2026-01-01").status_code
        == 422
    )
    assert get(harness, "/trajectory/records", agent_id="007").status_code == 422
    assert get(harness, "/trajectory/records", tenant_id="t2").status_code == 404
    assert get(harness, "/trajectory/records", actor="user").status_code == 403
    conversation = data(
        get(harness, "/trajectory/records", view="conversation", id_query=second.model1)
    )
    assert conversation["total"] == 1
    row = conversation["items"][0]
    assert row["round_count"] == 3 and row["matching_execution_count"] == 1
    assert row["status"] == "success" and row["duration_ms"] == 8000
    assert conversation["summary"]["duration"]["mean_ms"] == 3000
    assert conversation["summary"]["conversation_duration"]["p50_ms"] == 3000
    assert (
        data(get(harness, "/trajectory/records", view="conversation", status="error"))[
            "total"
        ]
        == 0
    )
    detail = data(
        get(
            harness,
            "/trajectory/conversations/123",
            query_id=conversation["query_id"],
            limit=1,
        )
    )
    assert detail["executions"][0]["round_no"] == 1
    assert detail["executions"][0]["matches_filters"] is False
    harness.add_run(status="failed", duration=7000)
    remaining = data(
        get(
            harness,
            "/trajectory/conversations/123",
            cursor=detail["next_cursor"],
            limit=20,
        )
    )
    assert [run["round_no"] for run in remaining["executions"]] == [2, 3]
    assert [run["matches_filters"] for run in remaining["executions"]] == [True, False]
    old = data(
        get(
            harness,
            "/trajectory/records",
            view="conversation",
            id_query=second.model1,
            query_id=conversation["query_id"],
        )
    )
    assert old["items"][0]["status"] == "success"
    assert (
        data(get(harness, "/trajectory/records", view="conversation"))["items"][0][
            "status"
        ]
        == "error"
    )
    harness.add_conversation("125", "t1", "u1")
    missing = data(
        get(harness, "/trajectory/records", view="conversation", status="not_captured")
    )
    assert missing["total"] == 1 and missing["items"][0]["conversation_id"] == "125"
    assert missing["items"][0]["duration_ms"] is None
    assert missing["summary"]["duration"]["sample_count"] == 0
    harness.now[0] += timedelta(days=40)
    expired = data(
        get(harness, "/trajectory/records", view="conversation", status="expired")
    )
    assert expired["total"] == 1 and expired["items"][0]["status"] is None
    assert expired["summary"]["duration"]["sample_count"] == 0
    assert get(harness, "/trajectory/records", status="expired").status_code == 422
    assert (
        get(
            harness,
            "/trajectory/records",
            view="conversation",
            query_id=conversation["query_id"],
        ).status_code
        == 422
    )
    harness.service.seconds = -1
    assert get(harness, "/trajectory/records").status_code == 503


def test_trj_query_keyless_references_remain_scoped_and_can_be_refreshed(harness):
    from management.services.trajectory.primitives import ReferenceStore

    view = snapshot(harness)
    tool = next(node for node in view["nodes"] if node["kind"] == "tool")
    content_id = tool["output"]["content_id"]
    assert len(content_id) == 32 and int(content_id, 16) >= 0
    prefix = "/trajectory/conversations/123/contents/"
    assert get(harness, prefix + content_id).status_code == 200
    for invalid in [content_id + "x", "a" * 32, view["snapshot_id"]]:
        response = get(harness, prefix + invalid)
        assert response.status_code == 422
        assert "text" not in response.json().get("data", {})
    assert get(harness, prefix + content_id, actor="admin2").status_code == 422
    assert get(harness, prefix + content_id, actor="user").status_code == 403
    harness.service.references = ReferenceStore()
    assert get(harness, prefix + content_id).status_code == 422
    refreshed = snapshot(harness)
    new_id = next(node for node in refreshed["nodes"] if node["kind"] == "tool")[
        "output"
    ]["content_id"]
    assert new_id != content_id
    assert get(harness, prefix + new_id).status_code == 200


@pytest.mark.parametrize("body_bytes", [1024 * 1024, 4 * 1024 * 1024])
def test_trj_query_large_unicode_content_roundtrip_and_reference_scope(
    harness, body_bytes
):
    body = ('中文😀\\"\n' * ((body_bytes // len('中文😀\\"\n'.encode())) + 1)) + "\n"
    harness.run = harness.add_run(body=body)
    view = snapshot(harness)
    tool = next(n for n in view["nodes"] if n["kind"] == "tool")
    output = tool["output"]
    assert output["char_count"] == len(body) and output["byte_count"] == len(
        body.encode()
    )
    assert output["text"] == body[: len(output["text"])] and not output["complete"]
    content_id = output["content_id"]
    path = "/trajectory/conversations/123/contents/" + content_id
    pieces, offset = [], 0
    while True:
        chunk = data(get(harness, path, offset=offset, limit=1048576))
        assert len(chunk["text"].encode()) <= 1048576
        pieces.append(chunk["text"])
        assert chunk["next_offset"] > offset
        offset = chunk["next_offset"]
        if chunk["complete"]:
            break
    assert "".join(pieces) == body
    assert get(harness, path + "x").status_code == 422
    assert get(harness, path, actor="admin2").status_code == 422
    assert get(harness, path.replace("/123/", "/124/")).status_code == 404
    assert get(harness, path, limit=1048577).status_code == 422
    forged = harness.service.references.resolve(content_id, "content")
    forged["field"] = "internal_file"
    bad = harness.service.references.issue("content", forged)
    assert (
        get(harness, "/trajectory/conversations/123/contents/" + bad).status_code == 422
    )


def test_trj_query_conversation_and_message_snapshot_bounds(harness, monkeypatch):
    harness.catalog.chat["123"] = {1: "第一条😀", 2: "第二条", 3: "第三条"}
    initial = data(
        get(harness, "/trajectory/conversations/123", include="messages", limit=1)
    )
    assert initial["trace_id"] == initial["conversation_id"] == "123"
    assert initial["coverage"]["chat"]["complete"] is True
    assert initial["coverage"]["chat"]["has_more"] is True
    assert initial["coverage"]["chat"]["message_id_upper"] == "3"
    assert initial["coverage"]["retention_window"]["execution_count"] == 1
    assert initial["coverage"]["retention_window"]["basis"] == "manifest"
    harness.add_run()
    harness.catalog.chat["123"][4] = "新消息"
    ids = [m["message_id"] for m in initial["messages"]]
    cursor = initial["message_cursor"]
    while cursor:
        page = data(
            get(
                harness,
                "/trajectory/conversations/123",
                include="messages",
                message_cursor=cursor,
                limit=1,
            )
        )
        ids.extend(m["message_id"] for m in page["messages"])
        assert len(page["executions"]) == 1
        assert page["coverage"]["chat"]["complete"] is True
        assert page["coverage"]["chat"]["message_id_upper"] == "3"
        assert page["coverage"]["retention_window"]["execution_count"] == 1
        cursor = page["message_cursor"]
    assert ids == ["1", "2", "3"]
    assert page["coverage"]["chat"]["has_more"] is False
    content = (
        "/trajectory/conversations/123/contents/" + initial["messages"][0]["content_id"]
    )
    assert data(get(harness, content))["text"] == "第一条😀"
    harness.catalog.chat["123"][1] = "已修改"
    assert get(harness, content).status_code == 409
    for replacement in ["响应前修改", None]:
        before = data(
            get(harness, "/trajectory/conversations/123", include="messages", limit=1)
        )
        reference = before["messages"][0]["content_id"]
        original_recheck = harness.service.recheck

        def changed_on_final_authorization(
            *args, original=original_recheck, value=replacement, **kwargs
        ):
            row = original(*args, **kwargs)
            if value is None:
                del harness.catalog.chat["123"][1]
            else:
                harness.catalog.chat["123"][1] = value
            return row

        with monkeypatch.context() as patch:
            patch.setattr(harness.service, "recheck", changed_on_final_authorization)
            response = get(
                harness, "/trajectory/conversations/123/contents/" + reference
            )
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "snapshot_reset"
        harness.catalog.chat["123"][1] = "已修改"
    fresh = data(get(harness, "/trajectory/conversations/123"))
    assert "messages" not in fresh
    assert fresh["coverage"]["chat"]["complete"] is None
    assert fresh["coverage"]["chat"]["reasons"] == ["not_requested"]
    assert len(fresh["executions"]) == 2
    harness.add_run(age_days=31)
    hidden_expiry = data(get(harness, "/trajectory/conversations/123", limit=1))
    assert hidden_expiry["executions"][0]["availability"] == "available"
    assert "expired" in hidden_expiry["coverage"]["conversation"]["reasons"]
    assert hidden_expiry["coverage"]["conversation"]["has_more"] is True
    assert hidden_expiry["coverage"]["retention_window"]["execution_count"] == 2


def test_trj_query_cleanup_fixed_cutoff_revocation_and_expiry(harness, caplog):
    caplog.set_level("INFO", logger="infrastructure.observability.trajectory_audit")
    harness.run = harness.add_run(age_days=10)
    view = snapshot(harness)
    body = next(n for n in view["nodes"] if n["kind"] == "tool")["output"]["content_id"]
    response = harness.client.post(
        "/trajectory/cleanup",
        json={"before_days": 7},
        headers={"Authorization": "admin"},
    )
    result = data(response)
    assert response.headers["cache-control"] == "private,no-store"
    assert result["deleted_runs"] == 1 and result["deleted_bytes"] > 0
    assert result["done"] and result["next_cursor"] is None
    (event,) = [
        json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
        for record in caplog.records
        if record.getMessage().startswith("trajectory.cleanup ")
    ]
    assert event["source"] == "manual" and event["actor_id"] == "admin"
    assert event["tenant_id"] == "t1" and event["before_days"] == 7
    assert event["cutoff_at"] == result["cutoff_at"]
    assert event["deleted_runs"] == result["deleted_runs"]
    assert event["deleted_bytes"] == result["deleted_bytes"]
    assert event["status"] == "success" and event["counts_complete"]
    assert (
        get(harness, "/trajectory/conversations/123/contents/" + body).status_code
        == 410
    )
    assert (
        get(
            harness,
            "/trajectory/conversations/123/snapshot",
            trajectory_id=harness.run.id,
            snapshot_id=view["snapshot_id"],
        ).status_code
        == 409
    )
    for days in [0, -1, 1.5, True, 3651]:
        assert (
            harness.client.post(
                "/trajectory/cleanup",
                json={"before_days": days},
                headers={"Authorization": "admin"},
            ).status_code
            == 422
        )
    assert (
        harness.client.post(
            "/trajectory/cleanup",
            json={"before_days": 7, "path": "/tmp"},
            headers={"Authorization": "admin"},
        ).status_code
        == 422
    )
    assert (
        harness.client.post(
            "/trajectory/cleanup",
            json={"before_days": 7},
            headers={"Authorization": "user"},
        ).status_code
        == 403
    )
    with (
        harness.store._root() as root,
        root.lock(".cleanup.lock"),
    ):
        busy = harness.client.post(
            "/trajectory/cleanup",
            json={"before_days": 7},
            headers={"Authorization": "admin"},
        )
        assert busy.status_code == 409 and busy.headers["retry-after"] == "2"
    events = [
        json.loads(record.getMessage().removeprefix("trajectory.cleanup "))
        for record in caplog.records
        if record.getMessage().startswith("trajectory.cleanup ")
    ]
    assert len(events) == 2
    assert events[-1]["status"] == "failed"
    assert events[-1]["error_code"] == "cleanup_busy"
    assert not events[-1]["counts_complete"]
    harness.catalog.members.remove(("t1", "u1"))
    assert get(harness, "/trajectory/conversations/123").status_code == 404


def test_trj_query_storage_states_and_tenant_migration(harness):
    harness.add_conversation("125")
    assert (
        data(get(harness, "/trajectory/conversations/125"))["availability"]
        == "not_captured"
    )
    assert get(harness, "/trajectory/conversations/123", actor=None).status_code == 401
    assert (
        get(harness, "/trajectory/conversations/123", actor="user").status_code == 403
    )
    assert (
        get(harness, "/trajectory/conversations/123", actor="admin2").status_code == 404
    )
    identity = harness.run.identity
    with harness.store._session(identity) as folder:
        fd = folder.open(harness.run.id + ".otlp.jsonl", os.O_WRONLY)
        os.pwrite(fd, b"X", 0)
        os.close(fd)
    corrupt = get(
        harness, "/trajectory/conversations/123/snapshot", trajectory_id=harness.run.id
    )
    assert (
        corrupt.status_code == 503
        and corrupt.json()["detail"]["code"] == "trajectory_corrupt"
    )
    harness.catalog.members.add(("t2", "u1"))
    harness.catalog.rows["123"]["tenant_id"] = "t2"
    assert (
        get(harness, "/trajectory/conversations/123", actor="admin2").status_code == 404
    )
    assert all(
        item["conversation_id"] != "123"
        for item in data(get(harness, "/trajectory/records", actor="su"))["items"]
    )
    marker = harness.root / ".storage-root.json"
    marker.unlink()
    assert get(harness, "/trajectory/conversations/125").status_code == 503


def test_trj_query_facets_and_only_declared_trajectory_routes(harness):
    harness.add_run(agent="8", model="other-model")
    options = data(
        get(
            harness, "/trajectory/records", facet="agents", target_user_id="u1", limit=1
        )
    )
    assert len(options["items"]) == 1 and options["next_cursor"]
    following = data(
        get(
            harness,
            "/trajectory/records",
            facet="agents",
            target_user_id="u1",
            limit=1,
            cursor=options["next_cursor"],
        )
    )
    assert options["items"][0]["id"] != following["items"][0]["id"]
    users = data(get(harness, "/trajectory/records", facet="users", actor="su"))
    assert {r["id"] for r in users["items"]} == {"u1", "u2"}
    models = data(get(harness, "/trajectory/records", facet="models", search="OTHER"))
    assert [m["id"] for m in models["items"]] == ["other-model"]
    routes = [
        (route.path, route.methods)
        for route in harness.app.routes
        if route.path.startswith("/trajectory/")
    ]
    assert sum("GET" in methods for _, methods in routes) == 5
    assert sum("POST" in methods for _, methods in routes) == 1
    assert sum("PUT" in methods for _, methods in routes) == 1


def test_trj_query_existing_directory_admin_branch_and_user_reuse(harness):
    own = harness.client.get(
        "/conversation/agent_groups", headers={"Authorization": "user"}
    )
    assert own.status_code == 200 and own.json()["data"]["included"] == [
        {"group_key": "agent:7"}
    ]
    own_conversations = harness.client.get(
        "/conversation/agent_groups/agent:7/conversations",
        headers={"Authorization": "user"},
    )
    assert own_conversations.status_code == 200
    users = harness.client.post(
        "/users/list",
        json={"tenant_id": "t1", "page": 1, "page_size": 20},
        headers={"Authorization": "admin"},
    )
    assert users.status_code == 200 and users.json()["pagination"]["total"] == 1
    assert users.json()["data"] == [{"user_id": "u1"}]
    branch = "/conversation/agent_groups"
    assert (
        data(get(harness, branch, view="trajectory", target_user_id="u1"))["items"][0][
            "agent_id"
        ]
        == "7"
    )
    assert (
        data(
            get(
                harness,
                branch + "/agent:7/conversations",
                view="trajectory",
                target_user_id="u1",
            )
        )["items"][0]["conversation_id"]
        == "123"
    )
    assert (
        get(
            harness, branch, view="trajectory", actor="user", target_user_id="u1"
        ).status_code
        == 403
    )
    assert get(harness, branch, view="trajectory").status_code == 422
    assert (
        get(harness, branch, view="trajectory", target_user_id="u2").status_code == 404
    )
    harness.add_conversation("125", agent=None, category="workbench")
    unknown = data(
        get(
            harness,
            branch,
            view="trajectory",
            target_user_id="u1",
            category="workbench",
        )
    )
    assert (
        unknown["items"][0]["group_key"] == "other"
        and unknown["included"] == unknown["pinned"] == []
    )
    harness.catalog.rows["123"]["agent_id"] = "8"
    switched = data(get(harness, branch, view="trajectory", target_user_id="u1"))
    assert switched["items"][0]["group_key"] == "agent:8"
    assert len(snapshot(harness)["nodes"]) == 5
    with harness.store._session(harness.run.identity) as folder:
        assert folder.read_json("meta.json")["agent_id"] == "7"
    # Two scoped groups give a signed cursor, which cannot be moved to another owner.
    harness.add_conversation("126", agent="9")
    page = data(get(harness, branch, view="trajectory", target_user_id="u1", limit=1))
    assert page["next_cursor"] and len(page["next_cursor"]) <= 2048
    assert (
        get(
            harness,
            branch,
            view="trajectory",
            target_user_id="u1",
            category="workbench",
            cursor=page["next_cursor"],
        ).status_code
        == 422
    )
    assert (
        harness.client.get(
            branch, params={"target_user_id": "u1"}, headers={"Authorization": "user"}
        ).status_code
        == 422
    )
    too_many = [("include_agent_id", "7")] * 101 + [
        ("view", "trajectory"),
        ("target_user_id", "u1"),
    ]
    assert (
        harness.client.get(
            branch, params=too_many, headers={"Authorization": "admin"}
        ).status_code
        == 422
    )


def test_trj_query_fragment_final_precedence_and_unknown_metrics(harness):
    harness.run = harness.add_run(fragment=True, missing_usage=True, duration=20)
    view = snapshot(harness)
    assert len(view["nodes"]) == 5
    root = next(n for n in view["nodes"] if n["id"] == harness.run.root)
    assert root["usage"]["total"] is None and not root["usage"]["complete"]
    assert root["usage"]["known"]["total"] == 25
    assert root["model_call_count"] == 2 and root["duration_ms"] == 20
    model = next(n for n in view["nodes"] if n["id"] == harness.run.model1)
    assert model["output"]["text"] == "回答" and model["usage"]["total"] is None


def test_trj_query_cleanup_batches_and_cursor_scope(harness):
    for number in range(124, 227):
        harness.add_conversation(str(number))
        harness.add_run(str(number), age_days=8)
    response = harness.client.post(
        "/trajectory/cleanup",
        json={"before_days": 7},
        headers={"Authorization": "admin"},
    )
    first = data(response)
    assert first["deleted_runs"] == 100 and first["scanned_runs"] <= 1000
    assert not first["done"] and first["next_cursor"]
    for actor, days, cursor in [
        ("admin2", 7, first["next_cursor"]),
        ("admin", 8, first["next_cursor"]),
        ("admin", 7, first["next_cursor"] + "x"),
    ]:
        assert (
            harness.client.post(
                "/trajectory/cleanup",
                json={"before_days": days, "cursor": cursor},
                headers={"Authorization": actor},
            ).status_code
            == 422
        )
    harness.now[0] += timedelta(hours=1)
    last = data(
        harness.client.post(
            "/trajectory/cleanup",
            json={"before_days": 7, "cursor": first["next_cursor"]},
            headers={"Authorization": "admin"},
        )
    )
    assert last["cutoff_at"] == first["cutoff_at"]
    assert last["deleted_runs"] == 3 and last["done"]
    assert (
        data(
            harness.client.post(
                "/trajectory/cleanup",
                json={"before_days": 3650},
                headers={"Authorization": "admin"},
            )
        )["deleted_runs"]
        == 0
    )


def test_trj_query_expiry_rechecks_cached_records_and_content(harness):
    view = snapshot(harness)
    body = next(n for n in view["nodes"] if n["kind"] == "tool")["output"]["content_id"]
    initial = data(get(harness, "/trajectory/records"))
    harness.now[0] += timedelta(days=31)
    assert (
        get(harness, "/trajectory/conversations/123/contents/" + body).status_code
        == 410
    )
    expired = data(get(harness, "/trajectory/records", query_id=initial["query_id"]))
    assert expired["items"][0]["trajectory_id"] is None
    assert expired["summary"]["duration"]["sample_count"] == 0
    harness.catalog.actors.pop("admin")
    assert get(harness, "/trajectory/conversations/123").status_code == 403


@pytest.mark.parametrize(
    "transition", ["expiry", "manual_cleanup", "membership_revoked"]
)
def test_trj_query_content_chunk_rechecks_state_after_physical_read(
    harness,
    monkeypatch,
    transition,
):
    from management.services.trajectory import service as service_module

    secret = "私有正文😀" * 4096
    harness.run = harness.add_run(body=secret, age_days=10)
    view = snapshot(harness)
    body = next(node for node in view["nodes"] if node["kind"] == "tool")["output"][
        "content_id"
    ]
    path = "/trajectory/conversations/123/contents/" + body
    first = data(get(harness, path, offset=0, limit=12))
    assert first["text"] and not first["complete"] and first["next_offset"] > 0
    run = next(
        item
        for item in harness.store.manifest(harness.run.identity)["runs"]
        if item["trajectory_id"] == harness.run.id
    )
    expires = parse_time(run["expires_at"])
    read_text = service_module.read_text
    observed = []

    def read_then_transition(*args, **kwargs):
        result = read_text(*args, **kwargs)
        observed.append(result["text"])
        assert result["text"]
        if transition == "expiry":
            harness.now[0] = expires
        elif transition == "manual_cleanup":
            removed = harness.store.cleanup(harness.run.identity, before_days=7)
            assert removed["deleted_runs"] == 1 and removed["failed_runs"] == 0
        else:
            harness.catalog.members.remove(("t1", "u1"))
        return result

    monkeypatch.setattr(service_module, "read_text", read_then_transition)
    response = get(harness, path, offset=first["next_offset"], limit=12)
    expected_status, expected_code = (
        (404, "trajectory_not_found")
        if transition == "membership_revoked"
        else (410, "content_expired")
    )
    assert len(observed) == 1
    assert response.status_code == expected_status
    assert response.json() == {"detail": {"code": expected_code}}
    assert observed[0] not in response.text and "text" not in response.json()
    repeated = get(harness, path, offset=first["next_offset"], limit=12)
    assert repeated.status_code == expected_status
    assert len(observed) == 1


def test_trj_query_incremental_parser_memory_and_source_boundaries(
    harness, record_property
):
    import time
    import tracemalloc

    body = '中😀\\"\n' * 400000
    harness.run = harness.add_run(body=body)
    harness.service.seconds = 60
    started = time.monotonic()
    tracemalloc.start()
    try:
        view = snapshot(harness)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("decoded_body_bytes", len(body.encode()))
    record_property("parser_peak_bytes", peak)
    record_property("cold_snapshot_seconds", time.monotonic() - started)
    assert peak < 32 * 1024 * 1024
    tool = next(n for n in view["nodes"] if n["kind"] == "tool")
    path = "/trajectory/conversations/123/contents/" + tool["output"]["content_id"]
    assert get(harness, path, offset=1).status_code == 422
    assert get(harness, path, offset=len(body.encode()) + 1).status_code == 422
    assert str(harness.root) not in json.dumps(view)
    data(get(harness, "/trajectory/records"))
    assert harness.service.summaries.size <= 32 * 1024 * 1024
    assert harness.service.queries.size <= 16 * 1024 * 1024


def test_trj_query_unarchived_partial_missing_and_snapshot_cleanup(harness):
    from uuid import uuid4

    harness.add_conversation("127")
    identity = type(harness.run.identity)("t1", "u1", "127", "7")
    run = str(uuid4())
    writer = harness.store.start(identity, run, str(uuid4()), core_type="smolagents")
    try:
        assert (
            get(
                harness, "/trajectory/conversations/127/snapshot", trajectory_id=run
            ).status_code
            == 409
        )
        conversation = data(get(harness, "/trajectory/conversations/127"))
        assert conversation["active_execution_count"] == 1
        assert conversation["availability"] == "unarchived"
        assert not conversation["coverage"]["complete"]
        assert "unarchived" in conversation["coverage"]["reasons"]
        pending = data(get(harness, "/trajectory/records", conversation_id="127"))
        assert pending["total"] == 1
        assert pending["items"][0]["trajectory_id"] is None
        assert pending["items"][0]["availability"] == "unarchived"
        assert pending["summary"]["duration"]["sample_count"] == 0
        assert pending["summary"]["ttft"]["sample_count"] == 0
        assert not pending["summary"]["coverage"]["complete"]
    finally:
        writer.close()
    harness.store.recover(identity, run)
    old = data(
        get(
            harness,
            "/trajectory/records",
            conversation_id="127",
            query_id=pending["query_id"],
        )
    )
    assert old["items"][0]["availability"] == "unarchived"
    assert old["items"][0]["trajectory_id"] is None
    refreshed = data(get(harness, "/trajectory/records", conversation_id="127"))
    assert refreshed["items"][0]["trajectory_id"] == run
    assert refreshed["items"][0]["availability"] == "partial"
    partial = data(
        get(harness, "/trajectory/conversations/127/snapshot", trajectory_id=run)
    )
    assert not partial["coverage"]["complete"] and partial["nodes"] == []
    initial = snapshot(harness)
    harness.add_run(age_days=10)
    data(
        harness.client.post(
            "/trajectory/cleanup",
            json={"before_days": 7},
            headers={"Authorization": "admin"},
        )
    )
    assert (
        get(
            harness,
            "/trajectory/conversations/123/snapshot",
            trajectory_id=harness.run.id,
            snapshot_id=initial["snapshot_id"],
        ).status_code
        == 409
    )
    with harness.store._session(harness.run.identity) as folder:
        os.unlink(harness.run.id + ".otlp.jsonl", dir_fd=folder.fd)
    missing = get(
        harness, "/trajectory/conversations/123/snapshot", trajectory_id=harness.run.id
    )
    assert (
        missing.status_code == 503
        and missing.json()["detail"]["code"] == "trajectory_corrupt"
    )


def test_trj_query_source_fallback_namespace_and_absent_reasoning(harness):
    harness.run = harness.add_run(legacy=True)
    view = snapshot(harness)
    assert view["root_node_id"].startswith("otel:" + ("a" * 32) + ":")
    assert all(n["id"].startswith("otel:") for n in view["nodes"])
    assert all(n["reasoning"]["availability"] == "not_returned" for n in view["nodes"])
    assert all(n["reasoning"]["text"] is None for n in view["nodes"])


def test_trj_query_managed_lane_capacity_rejection(harness):
    import threading

    from nexent.core.concurrency import (
        ManagedTaskSpec,
        ThreadCapacityExceeded,
        ThreadQueueTimedOut,
    )

    manager = harness.app.state.thread_manager
    release = threading.Event()
    executions = []
    try:
        for index in range(4):
            try:
                executions.append(
                    manager.submit(
                        "trajectory-read",
                        ManagedTaskSpec("fixture-block-" + str(index), "query-case"),
                        release.wait,
                        10,
                    )
                )
            except ThreadCapacityExceeded:
                break
        response = get(harness, "/trajectory/records")
        assert response.status_code == 503
        assert (
            response.json()["detail"]["code"] == "query_busy"
            and response.headers["retry-after"] == "2"
        )
    finally:
        release.set()
        for execution in executions:
            try:
                execution.future.result(timeout=3)
            except ThreadQueueTimedOut:
                pass


def test_trj_query_unauthorized_identity_is_401_and_private(harness, monkeypatch):
    from contracts.errors.exceptions import UnauthorizedError
    from management.api.observability import trajectory as api

    def denied(_):
        raise UnauthorizedError("Internal credential reason must remain private")

    monkeypatch.setattr(api, "get_current_user_context", denied)
    response = get(harness, "/trajectory/records")
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "unauthenticated"}}


def test_trj_query_private_validation_under_api_root(harness):
    harness.app.root_path = "/api"
    response = get(
        harness,
        "/trajectory/conversations/123/snapshot",
        trajectory_id=harness.run.id,
        limit=501,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_parameters"}}


def test_trj_query_pg_list_uses_snapshot_without_opening_archives(harness, monkeypatch):
    """Controlled PG results cross the real HTTP boundary; detail still opens the actual archive."""
    from datetime import UTC, datetime
    from unittest.mock import Mock

    from management.db.trajectory.queries import ExecutionCatalog
    from management.services.trajectory.cache import ByteCache
    from management.services.trajectory.projection import execution_values

    original_manifest = harness.service.archive.manifest
    row = harness.catalog.resolve(["t1"], "123")
    meta = original_manifest(row)
    from management.services.trajectory.access import Actor

    nodes, root, _ = harness.service.load(
        Actor("admin", "t1", "ADMIN"), row, harness.run.id, harness.service.budget()
    )
    values = execution_values("123", meta["runs"][0], nodes, root)
    projected = ExecutionCatalog._dto(
        {
            **row,
            **values,
            "runs": [
                {
                    "id": harness.run.id,
                    "status": values["status"],
                    "turn": 1,
                    "matches": True,
                }
            ],
            "execution_count": 1,
            "matching_execution_count": 1,
            "cumulative_duration_ms": values["duration_ms"],
            "cumulative_input_tokens": values["input_tokens"],
            "cumulative_output_tokens": values["output_tokens"],
            "cumulative_total_tokens": values["total_tokens"],
        },
        "conversation",
    )
    summary = {
        "complete": True,
        "conversation_count": 9,
        "computed_at": datetime.now(UTC).isoformat(),
        "scope_type": "tenant",
        "scope_id": "t1",
        "computed_revision": 3,
        "source_revision": 4,
    }
    catalog = Mock()
    catalog.list_records.return_value = [projected]
    catalog.statistics.return_value = summary
    catalog.facets.return_value = [{"id": "m", "name": "model", "tenant_id": "t1"}]
    harness.service.execution_catalog = catalog
    harness.service.queries = ByteCache()

    def forbidden(*args, **kwargs):
        raise AssertionError("List attempted a filesystem read")

    monkeypatch.setattr(harness.service.archive, "manifest", forbidden)
    monkeypatch.setattr(harness.service, "load", forbidden)
    first = data(
        get(
            harness,
            "/trajectory/records",
            view="conversation",
            id_query="123",
            page_size=1,
        )
    )
    assert first["items"][0]["conversation_id"] == "123" and first["summary"] == summary
    catalog.list_records.assert_called_once()
    second = data(
        get(
            harness,
            "/trajectory/records",
            view="conversation",
            id_query="123",
            page=2,
            query_id=first["query_id"],
            page_size=1,
        )
    )
    assert (
        second["total"] == 1 and second["items"] == [] and second["summary"] == summary
    )
    catalog.list_records.assert_called_once()
    filtered = data(
        get(harness, "/trajectory/records", view="conversation", model="absent")
    )
    assert filtered["summary"] == summary
    assert (
        data(get(harness, "/trajectory/records", facet="models"))["items"][0]["id"]
        == "m"
    )
    catalog.validate.side_effect = QueryError("snapshot_reset", 409)
    assert (
        get(
            harness,
            "/trajectory/records",
            view="conversation",
            id_query="123",
            query_id=first["query_id"],
        ).status_code
        == 409
    )
    catalog.validate.side_effect = None
    monkeypatch.setattr(harness.service.archive, "manifest", original_manifest)
    # The real snapshot reader has independent permissions and file confirmation.
    from management.services.trajectory.service import TrajectoryService

    monkeypatch.setattr(
        harness.service, "load", TrajectoryService.load.__get__(harness.service)
    )
    detail = data(
        get(harness, "/trajectory/conversations/123", query_id=first["query_id"])
    )
    assert detail["executions"][0]["trajectory_id"] == harness.run.id
    assert snapshot(harness)["nodes"]


def test_trj_query_tenant_cleanup_schedule_persists_and_rejects_other_scopes(harness, monkeypatch):
    from types import SimpleNamespace

    from management.services.trajectory import cleanup_schedule as settings

    values = {}
    repository = SimpleNamespace(
        read=lambda tenant: values.get(tenant),
        save=lambda tenant, seconds, actor: values.update({tenant: seconds}),
    )
    monkeypatch.setattr(settings, "CleanupScheduleRepository", lambda: repository)
    monkeypatch.setattr(settings, "TrajectoryCatalog", lambda: harness.catalog)
    monkeypatch.setattr(settings.config, "TRAJECTORY_CLEANUP_INTERVAL_SECONDS", 3600)
    monkeypatch.setattr(settings.config, "TRAJECTORY_CLEANUP_ENABLED", True)
    monkeypatch.setattr(settings.config, "TRAJECTORY_RETENTION_DAYS", 30)
    # Settings must remain available even when the trajectory file mount is unavailable.
    from management.api.observability import trajectory as api
    monkeypatch.setattr(api, "get_service", lambda: (_ for _ in ()).throw(OSError("unmounted")))
    path = "/trajectory/cleanup/schedule"
    assert data(get(harness, path))["interval_seconds"] == 3600
    for actor, tenant, seconds in [("admin", "t1", 60), ("su", "t2", 31536000)]:
        saved = harness.client.put(path, json={"tenant_id": tenant, "interval_seconds": seconds},
                                   headers={"Authorization": actor})
        assert data(saved) == {"tenant_id": tenant, "interval_seconds": seconds, "enabled": True, "retention_days": 30}
        assert saved.headers["cache-control"] == "private,no-store"
        assert data(get(harness, path, actor=actor, tenant_id=tenant))["interval_seconds"] == seconds
    assert values == {"t1": 60, "t2": 31536000}
    assert get(harness, path, actor="admin", tenant_id="t2").status_code == 404
    assert harness.client.put(path, json={"tenant_id": "t2", "interval_seconds": 120},
                              headers={"Authorization": "admin"}).status_code == 404
    assert get(harness, path, actor="user").status_code == 403
    assert harness.client.put(path, json={"interval_seconds": 120},
                              headers={"Authorization": "user"}).status_code == 403
    for value in [59, 31536001, 60.5, "60", True]:
        invalid = harness.client.put(path, json={"interval_seconds": value}, headers={"Authorization": "admin"})
        assert invalid.status_code == 422 and invalid.headers["cache-control"] == "private,no-store"
    assert harness.client.put(path, json={"interval_seconds": 120, "path": "injected"},
                              headers={"Authorization": "admin"}).status_code == 422
    assert values == {"t1": 60, "t2": 31536000}
    repository.save = lambda *args: (_ for _ in ()).throw(ConnectionError("private PG details"))
    unavailable = harness.client.put(path, json={"interval_seconds": 120}, headers={"Authorization": "admin"})
    assert unavailable.status_code == 503 and "private PG details" not in unavailable.text
    assert values["t1"] == 60
    harness.catalog.actors.pop("admin")
    assert get(harness, path).status_code == 403
