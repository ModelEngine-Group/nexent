# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit checks for resource workflow state transitions."""

from unittest.mock import AsyncMock

import pytest
from nexent.core import concurrency
from nexent.core.tools.send_email_tool import SendEmailTool

from contracts.nl2agent_resources import (
    RequirementEdit, ResourceCardAction, ResourceInstallationRequest, ResourceLinkRequest, VerificationCheck,
)
from backend.mcp.thread_management import mcp_thread_manager
from management.db.mcp import remote
from management.db.tool import outer_api
from management.services.mcp import service as mcp_service
from services import nl2agent_resource_flow as flow
from services.nl2agent_resource_flow import apply_requirement_edits, validate_checks
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.mark.asyncio
async def test_coverage_card_distinguishes_existing_and_uninstalled_repository_mcps(monkeypatch):
    # This fixture isolates installation-status rendering; source authorization
    # is covered with complete resource declarations in its dedicated suite.
    monkeypatch.setattr(flow, "_authorized_batch_result", AsyncMock())
    scope = ResourceScope("tenant", "user", 1, "4", "run")
    candidates = [
        {"candidate_ref": f"tenant_mcp_repository:{market_id}", "source": "TENANT_MCP_REPOSITORY"}
        for market_id in range(1, 5)
    ]
    state = {
        "conversation_id": "4", "run_id": "run", "version": 2, "purpose": "generate",
        "card": None, "batch": None,
        "requirements": {"tickets": {
            "query": "Train tickets", "installable": candidates,
            "accepted": [candidate["candidate_ref"] for candidate in candidates],
        }},
    }
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))

    async def update(_scope, change):
        state.update(change(state))
        return state

    monkeypatch.setattr(flow, "update_resource_state", update)
    monkeypatch.setattr(mcp_service, "get_mcp_records_by_tenant", lambda **_: [
        {"market_id": 1, "enabled": False, "group_ids": "", "created_by": "user"},
        {"market_id": 2, "enabled": True, "group_ids": None},
        {"market_id": 2, "enabled": False, "group_ids": None},
        {"market_id": 3, "enabled": False, "group_ids": "", "created_by": "another-user"},
    ])
    monkeypatch.setattr(mcp_service, "query_group_ids_by_user", lambda _: [])

    manager = concurrency.ThreadManager("nl2agent-mcp-fixture", mcp_thread_manager._policies)
    manager.start()
    monkeypatch.setattr(concurrency.helpers, "get_default_thread_manager", lambda: manager)
    try:
        card = await flow.show_card(scope)
        row = card["requirements"][0]
        assert row["covered_resources"] == []
        assert [item.get("installation_status") for item in row["installable_resources"]] == [
            "disabled", "installed", None, None,
        ]
        details = await flow.installation_details(scope, ResourceInstallationRequest(
            agent_id=scope.agent_id, conversation_id=int(scope.conversation_id),
            card_id=card["card_id"], state_version=card["state_version"],
            requirement_id="tickets", candidate_ref=candidates[0]["candidate_ref"],
        ))
        assert details["installation_status"] == "disabled"
        assert details["resources"] == []
    finally:
        await manager.shutdown(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(("enabled", "available", "already_reviewed"), [
    (False, True, False), (True, False, False), (True, True, True), (True, True, False),
])
async def test_confirmation_rechecks_only_new_tools_from_enabled_repository_mcp(
    monkeypatch, enabled, available, already_reviewed,
):
    scope = ResourceScope("tenant", "user", 1, "4", "next")
    ref = "tenant_mcp_repository:3"
    email = {"query": "Send email", "installed": [{"candidate_ref": "tool:1"}], "accepted": ["tool:1"]}
    state = {
        "conversation_id": "4", "run_id": "run", "version": 2, "purpose": "generate",
        "card": {"id": "card", "subtype": "requirement_resources"}, "batch": None,
        "requirements": {
            "email": email,
            "tickets": {"query": "Check real-time 12306 ticket availability",
                        "installed": [{"candidate_ref": "tool:7"}] if already_reviewed else [],
                        "installable": [{"candidate_ref": ref, "source": "TENANT_MCP_REPOSITORY"}],
                        "accepted": [ref]},
        },
    }
    tool = {
        "candidate_ref": "tool:7", "resource_type": "tool", "source": "MCP_TOOL", "name": "get_tickets",
        "description": "查询余票", "names": ["get_tickets"], "labels": [], "descriptions": ["查询余票"],
        "interfaces": [], "installed": True, "mcp_service_name": "12306 local",
    }
    monkeypatch.setattr(flow, "_visible_repository_mcps", AsyncMock(return_value={
        ref: [{"enabled": enabled, "mcp_name": "12306 local"}],
    }))
    catalog = [tool] if available else [{**tool, "mcp_service_name": "Unrelated MCP"}]
    monkeypatch.setattr(flow.legacy, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(flow.legacy, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))
    monkeypatch.setattr(flow, "show_card", AsyncMock(return_value={"subtype": "requirement_resources"}))

    async def update(_scope, change):
        state.update(change(state))
        return state

    monkeypatch.setattr(flow, "update_resource_state", update)
    result = await flow.apply_card_action(scope, "requirement_resources", "confirm_requirements", ResourceCardAction(
        card_id="card", state_version=2, requirements=[
            RequirementEdit(requirement_id=key, query=row["query"]) for key, row in state["requirements"].items()
        ],
    ))
    if enabled and available and not already_reviewed:
        assert result["next_step"] == "verify_resources"
        batch = await flow.discover(scope, None, "generate")
        [requirement] = batch["requirements"]
        assert requirement["requirement_id"] == "tickets"
        assert [item["candidate_ref"] for item in requirement["installed_candidates"]] == ["tool:7"]
    else:
        assert result["card"]["subtype"] == "requirement_resources"
        assert state["requirements"]["tickets"]["accepted"] == [ref]
    assert state["requirements"]["email"]["accepted"] == ["tool:1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trusted_retry", "version", "error"),
    [(True, 3, None), (False, 3, "resource_card_stale"), (True, 4, "resource_card_stale")],
)
async def test_coverage_retry_resumes_saved_edits_only_for_current_failed_confirmation(
    monkeypatch, trusted_retry, version, error,
):
    scope = ResourceScope("tenant", "user", 1, "4", "retry-run")
    state = {
        "conversation_id": "4", "version": version, "purpose": "generate", "run_id": "failed-run",
        "card": None, "requirements": {"r2": {"query": "weather", "required": True}},
        "next_requirement_id": 3,
    }
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))

    async def update(_scope, change):
        state.update(change(state))
        return state

    monkeypatch.setattr(flow, "update_resource_state", update)
    payload = ResourceCardAction(card_id="old-card", state_version=2, requirements=[
        RequirementEdit(client_key="new", query="weather"),
    ])
    if error:
        with pytest.raises(ResourceStateError, match=error):
            await flow.apply_card_action(
                scope, "requirement_resources", "confirm_requirements", payload, resume_confirmation=trusted_retry,
            )
        assert state["run_id"] == "failed-run"
    else:
        result = await flow.apply_card_action(
            scope, "requirement_resources", "confirm_requirements", payload, resume_confirmation=trusted_retry,
        )
        assert result["next_step"] == "verify_resources"
        assert state["run_id"] == "retry-run"
    assert list(state["requirements"]) == ["r2"]
    assert state["next_requirement_id"] == 3


@pytest.mark.parametrize(
    ("query", "search_query", "expected"),
    [
        ("发送邮件", None, ["send_email"]), ("发送一封邮件", None, ["send_email"]),
        ("send_email", None, ["send_email"]), ("接收邮件", None, []),
        ("根据用户提供的周报和异常记录生成总结，按指定模板编排邮件主题与正文，并将结果发送给指定收件人和抄送人员",
         "发送邮件", ["send_email"]),
    ],
)
def test_send_email_is_recalled_for_send_requests(query, search_query, expected):
    catalog = [{
        "candidate_ref": "tool:8",
        "resource_type": "tool",
        "source": "LOCAL_TOOL",
        "name": SendEmailTool.name,
        "description": SendEmailTool.description,
        "names": [SendEmailTool.name],
        "labels": ["email"],
        "descriptions": [SendEmailTool.description, SendEmailTool.description_zh],
        "interfaces": flow.legacy._flatten_resource_text(SendEmailTool.inputs),
        "installed": True,
        "quality": 1.0,
    }]
    assert [row["name"] for row in flow._rank("email", query, catalog, search_query=search_query)] == expected


def test_unchanged_requirements_reuse_evidence_and_new_rows_get_ids():
    accepted = {
        "query": "weather", "search_query": "forecast", "required": True,
        "accepted": ["tool:8"], "installed": [],
    }
    previous = {"requirements": {
        "keep": accepted,
        "edit": {"query": "search", "search_query": "database", "required": True, "accepted": ["tool:7"]},
        "delete": {"query": "unused", "required": False},
    }, "batch": {"id": "old"}}
    result = apply_requirement_edits(previous, [
        RequirementEdit(requirement_id="keep", query="weather", required=False),
        RequirementEdit(requirement_id="edit", query="search public pages"),
        RequirementEdit(client_key="new", query="live ticket availability"),
    ])
    assert result["requirements"]["keep"] == accepted
    assert result["requirements"]["edit"] == {"query": "search public pages", "required": True}
    new_id = result["client_keys"]["new"]
    assert new_id == "r1" and result["requirements"][new_id]["query"] == "live ticket availability"
    assert "delete" not in result["requirements"]
    assert result["batch"] is None
    replaced = apply_requirement_edits(result, [RequirementEdit(client_key="next", query="flight status")])
    assert replaced["client_keys"] == {"next": "r2"}


def test_manual_links_follow_submitted_client_keys_and_clear_old_verification():
    previous = {
        "requirements": {"weather": {"query": "weather", "required": True,
                                     "linked_refs": ["skill:1"], "needs_link_verification": True,
                                     "accepted": ["tool:8"], "installed": [], "installable": []}},
        "pending_links": {"added": ["tool:2"], "removed": ["skill:3"]},
    }
    result = apply_requirement_edits(previous, [
        RequirementEdit(requirement_id="weather", query="weather"),
        RequirementEdit(client_key="added", query="airport arrivals"),
    ])
    assert result["requirements"]["weather"] == {
        "query": "weather", "required": True, "linked_refs": ["skill:1"],
    }
    assert result["requirements"][result["client_keys"]["added"]]["linked_refs"] == ["tool:2"]
    assert result["pending_links"] == {}
    assert "removed" not in result["client_keys"]


@pytest.mark.asyncio
async def test_deleting_all_requirements_explicitly_resumes_generation_without_resources(monkeypatch):
    scope = ResourceScope("tenant", "user", 1, "4", "run")
    state = {
        "conversation_id": "4", "version": 2, "purpose": "generate",
        "card": {"id": "card", "subtype": "requirement_resources"},
        "requirements": {"weather": {"query": "weather", "required": True}},
    }
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))

    async def update(_scope, change):
        state.update(change(state))
        return state

    monkeypatch.setattr(flow, "update_resource_state", update)
    result = await flow.apply_card_action(
        scope, "requirement_resources", "confirm_requirements",
        ResourceCardAction(card_id="card", state_version=2, requirements=[]),
    )
    assert state["requirements"] == {}
    assert result == {
        "purpose": "generate", "action": "confirm_requirements",
        "confirmed_requirements": [], "next_step": "generate_prompt",
    }


@pytest.mark.parametrize(
    ("checked", "accepted", "error"),
    [
        ([], [], "verification_candidates_incomplete"),
        (["tool:8", "tool:8"], ["tool:8"], "verification_candidates_incomplete"),
        (["tool:8"], ["tool:9"], "invalid_verified_candidate"),
        (["tool:8"], [], None),
        (None, ["tool:8"], None),
        (None, ["tool:9"], "invalid_verified_candidate"),
    ],
)
def test_verification_distinguishes_empty_acceptance_from_missing_or_foreign_candidates(checked, accepted, error):
    state = {
        "batch": {"id": "batch", "requirements": ["req"]},
        "requirements": {"req": {"installed": [{"candidate_ref": "tool:8"}], "installable": []}},
    }
    checks = [VerificationCheck(requirement_id="req", checked=checked, accepted=accepted)]
    if error:
        with pytest.raises(ResourceStateError, match=error):
            validate_checks(state, "batch", checks)
    else:
        assert validate_checks(state, "batch", checks) == {"req": accepted}


@pytest.mark.asyncio
async def test_retry_accepts_the_same_selection_without_echoing_legacy_checked_refs(monkeypatch):
    scope = ResourceScope("tenant", "user", 1, "4", "run")
    state = {
        "conversation_id": "4", "run_id": "run", "batch": None, "requirements": {},
        "submitted_batches": {"batch": [["r1", ["tool:8", "tool:9"], ["tool:8"]]]},
    }
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))
    result = await flow.verify(scope, "batch", [VerificationCheck(requirement_id="r1", accepted=["tool:8"])])
    assert result["verification_batch_id"] is None
    with pytest.raises(ResourceStateError, match="verification_batch_conflict"):
        await flow.verify(scope, "batch", [VerificationCheck(requirement_id="r1", accepted=["tool:9"])])


@pytest.mark.asyncio
async def test_stale_batch_cannot_receive_current_candidates_or_advance_verification(mocker):
    scope = ResourceScope("tenant", "user", 1, "4", "run")
    mocker.patch.object(flow, "read_resource_state", return_value={
        "conversation_id": "4", "run_id": "run", "batch": {"id": "current"}, "requirements": {},
    })
    read_current_candidates = mocker.patch.object(flow, "_authorized_batch_result")
    persist = mocker.patch.object(flow, "update_resource_state")

    with pytest.raises(ResourceStateError, match="verification_batch_stale") as outcome:
        await flow.verify(scope, "previous", [])

    assert not outcome.value.retryable
    read_current_candidates.assert_not_awaited()
    persist.assert_not_awaited()


def test_resource_state_key_is_isolated_by_tenant_user_agent_and_conversation():
    base = ResourceScope("tenant", "user", 1, "conversation", "run")
    scopes = [base, ResourceScope("other", "user", 1, "conversation", "run"),
              ResourceScope("tenant", "other", 1, "conversation", "run"),
              ResourceScope("tenant", "user", 2, "conversation", "run"),
              ResourceScope("tenant", "user", 1, "other", "run")]
    assert len({scope.key for scope in scopes}) == len(scopes)


@pytest.mark.asyncio
@pytest.mark.parametrize(("owner", "openapi"), [("user", False), ("other-user", False), ("user", True)])
async def test_manual_mcp_link_resolves_all_tools_from_the_owned_service(monkeypatch, owner, openapi):
    scope = ResourceScope("tenant", "user", 1, "4", "run")
    state = {"conversation_id": "4", "version": 2, "purpose": "generate",
             "card": {"id": "card", "subtype": "requirement_resources"}, "requirements": {}}
    catalog = [
        {"source": "MCP_TOOL", "candidate_ref": f"tool:{index}",
         "mcp_service_name": "outer-apis" if openapi else "new-service", "names": [f"new-service_read_{index}"]}
        for index in range(1, 6)
    ] + [{"source": "MCP_TOOL", "candidate_ref": "tool:99",
          "mcp_service_name": "outer-apis" if openapi else "other-service", "names": ["new-service_other_read"]}]
    monkeypatch.setattr(flow, "read_resource_state", AsyncMock(return_value=state))
    monkeypatch.setattr(flow.legacy, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(remote, "get_mcp_record_by_id_and_tenant",
                        lambda mcp_id, tenant_id: {"mcp_name": "new-service", "created_by": owner,
                                                    "config_json": {"openapi": "3.0.0"} if openapi else None}
                        if (mcp_id, tenant_id) == (17, "tenant") else None)
    monkeypatch.setattr(outer_api, "query_available_openapi_services", lambda _: [
        {"mcp_service_name": "new-service"}, {"mcp_service_name": "new-service_other"},
    ])

    async def execute(_name, function, *args, **_kwargs):
        return function(*args)

    async def update(_scope, change):
        state.update(change(state))

    monkeypatch.setattr(concurrency, "run_blocking", execute)
    monkeypatch.setattr(flow, "update_resource_state", update)
    request = ResourceLinkRequest(agent_id=1, conversation_id=4, card_id="card", state_version=2,
                                  client_key="manual", resource_type="mcp_server", resource_id=17)
    if owner != scope.user_id:
        with pytest.raises(ResourceStateError, match="installed_resource_not_visible"):
            await flow.link_installed_resource(scope, request)
        assert "pending_links" not in state
        return
    await flow.link_installed_resource(scope, request)
    await flow.link_installed_resource(scope, request)
    assert state["pending_links"] == {"manual": [f"tool:{index}" for index in range(1, 6)]}
