import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import MagicMock

import fakeredis
import pytest

from agents import nl2agent_session_catalog as catalog_module
from agents import nl2agent_session_store as session_store


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        catalog_module,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    initial_state = catalog_module.initialize_nl2agent_session_state(
        "tenant_1", 202, conversation_id=902
    )
    durable_snapshot = {
        "tenant_id": "tenant_1",
        "draft_agent_id": 202,
        "status": "active",
        "workflow_revision": 0,
        "workflow_state": initial_state,
        "session_catalogs": _catalogs(),
    }

    def load_durable_session(tenant_id, draft_agent_id):
        if tenant_id != "tenant_1" or draft_agent_id != 202:
            return None
        return deepcopy(durable_snapshot)

    def persist_workflow_state(
        tenant_id, draft_agent_id, expected_revision, workflow_state
    ):
        if tenant_id != "tenant_1" or draft_agent_id != 202:
            return False
        if durable_snapshot["workflow_revision"] != expected_revision:
            return False
        durable_snapshot["workflow_revision"] = workflow_state["revision"]
        durable_snapshot["workflow_state"] = deepcopy(workflow_state)
        return True

    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(side_effect=load_durable_session)
    )
    monkeypatch.setattr(
        session_store,
        "persist_workflow_state",
        MagicMock(side_effect=persist_workflow_state),
    )
    cache_catalogs = catalog_module.set_nl2agent_session_catalogs

    def set_session_catalogs(tenant_id, draft_agent_id, catalogs):
        if tenant_id == "tenant_1" and draft_agent_id == 202:
            durable_snapshot["session_catalogs"] = deepcopy(catalogs)
        return cache_catalogs(tenant_id, draft_agent_id, catalogs)

    monkeypatch.setattr(
        catalog_module, "set_nl2agent_session_catalogs", set_session_catalogs
    )
    return client


def _catalogs():
    return {
        "tool_catalog": [{"tool_id": 1}],
        "skill_catalog": [{"skill_id": 2}],
        "registry_results": [],
        "community_results": [],
        "official_skills": [],
    }


def _register_local_batch(batch_id, tool_ids, skill_ids):
    catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id=batch_id,
        resource_type="local",
        tool_ids=tool_ids,
        skill_ids=skill_ids,
    )
    return catalog_module.register_recommendation_batch(
        "tenant_1", 202, batch_id, tool_ids, skill_ids
    )


def _complete_local_apply(batch_id, tool_ids, skill_ids):
    operation_id = f"test-apply:{batch_id}"
    catalog_module.reserve_recommendation_batch_apply(
        "tenant_1", 202, batch_id, operation_id, tool_ids, skill_ids
    )
    return catalog_module.complete_recommendation_batch_apply(
        "tenant_1", 202, batch_id, operation_id
    )


def _register_online_batch(batch_id, resource_type, item_keys):
    catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id=batch_id,
        resource_type=resource_type,
        item_keys=item_keys,
    )
    return catalog_module.register_online_recommendation_batch(
        "tenant_1", 202, batch_id, resource_type, item_keys
    )


def _prepare_online_review():
    review = catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Build an agent",
            "audience_or_scenario": "Operators",
            "primary_input": "Requests",
            "expected_output": "Actions",
            "key_constraints": "Use trusted resources",
        },
    )
    catalog_module.confirm_requirements_summary(
        "tenant_1", 202, review["fingerprint"]
    )
    catalog_module.set_model_selection_confirmed("tenant_1", 202, True)
    _register_local_batch("local_empty", [], [])
    catalog_module.resolve_recommendation_batch(
        "tenant_1", 202, "local_empty", "skipped"
    )
    _register_online_batch("online_mcp", "mcp", [])
    _register_online_batch("online_skill", "skill", ["skill:12"])


def _prepare_final_review():
    _prepare_online_review()
    catalog_module.complete_online_configuration("tenant_1", 202)
    catalog_module.confirm_agent_identity("tenant_1", 202)
    catalog_module.record_card_delivery(
        "tenant_1", 202, 71, "final_review", "rendered"
    )


def test_catalogs_round_trip_through_authoritative_session(fake_redis):
    catalog_module.set_nl2agent_session_catalogs("tenant_1", 202, _catalogs())
    assert catalog_module.get_nl2agent_session_catalogs("tenant_1", 202) == _catalogs()


def test_search_projection_hides_installed_mcp_and_marks_installed_skill(
    fake_redis,
):
    catalogs = {
        **_catalogs(),
        "registry_results": [{"server": {"name": "github"}}],
        "community_results": [{"communityId": 55, "name": "browser"}],
        "official_skills": [
            {
                "skill_id": 12,
                "skill_name": "code-review",
                "status": "installable",
            }
        ],
    }
    catalog_module.set_nl2agent_session_catalogs("tenant_1", 202, catalogs)
    workflow_state = {
        "mcp_workflows": {
            "registry:github": {"status": "tools_bound"},
        },
        "online_installations": {
            "skill:12": {
                "status": "completed",
                "result": {
                    "skill_id": 112,
                    "skill_name": "code-review",
                },
            }
        },
    }

    projected = catalog_module.get_nl2agent_search_catalogs(
        "tenant_1", 202, workflow_state
    )

    assert projected["registry_results"] == []
    assert projected["community_results"] == catalogs["community_results"]
    assert projected["official_skills"][0]["status"] == "installed"
    assert catalog_module.get_nl2agent_session_catalogs("tenant_1", 202) == catalogs


def test_missing_catalogs_raise_contextual_error(fake_redis, monkeypatch):
    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(return_value=None)
    )
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)

def test_malformed_catalogs_are_rejected_from_database(fake_redis, monkeypatch):
    snapshot = session_store.load_durable_session("tenant_1", 202)
    snapshot["session_catalogs"] = {"tool_catalog": "not-a-list"}
    monkeypatch.setattr(session_store, "load_durable_session", MagicMock(return_value=snapshot))

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="field 'tool_catalog' is malformed",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)

def test_recommendation_batch_registration_is_idempotent_and_requires_resolution(
    fake_redis,
):
    first = _register_local_batch("batch_1", [3, 1], [7])
    second = _register_local_batch("batch_1", [3, 1], [7])
    assert first == second
    assert first["status"] == "recommendations_ready"

    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Apply or skip"):
        catalog_module.assert_resource_review_complete("tenant_1", 202)

    _complete_local_apply("batch_1", [1], [7])
    catalog_module.assert_resource_review_complete("tenant_1", 202)


def test_local_apply_and_skip_cannot_both_reserve_the_same_batch(fake_redis):
    _register_local_batch("race", [1], [])

    def reserve_apply():
        return catalog_module.reserve_recommendation_batch_apply(
            "tenant_1", 202, "race", "apply-op", [1], []
        )

    def skip_batch():
        return catalog_module.resolve_recommendation_batch(
            "tenant_1", 202, "race", "skipped"
        )

    successes = []
    failures = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve_apply), executor.submit(skip_batch)]
        for future in futures:
            try:
                successes.append(future.result())
            except catalog_module.Nl2AgentSessionCatalogError as exc:
                failures.append(exc)

    assert len(successes) == 1
    assert len(failures) == 1
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["recommendation_batches"]["race"]["status"] in {
        "applying",
        "skipped",
    }


def test_completed_local_apply_is_idempotent_only_for_its_owner(fake_redis):
    _register_local_batch("batch_1", [1], [])
    catalog_module.reserve_recommendation_batch_apply(
        "tenant_1", 202, "batch_1", "apply-op", [1], []
    )
    catalog_module.complete_recommendation_batch_apply(
        "tenant_1", 202, "batch_1", "apply-op"
    )

    retried = catalog_module.reserve_recommendation_batch_apply(
        "tenant_1", 202, "batch_1", "apply-op", [1], []
    )
    assert retried["status"] == "applied"
    catalog_module.complete_recommendation_batch_apply(
        "tenant_1", 202, "batch_1", "apply-op"
    )

    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="resolved"):
        catalog_module.reserve_recommendation_batch_apply(
            "tenant_1", 202, "batch_1", "other-op", [1], []
        )


def test_empty_recommendation_batch_can_be_explicitly_skipped(fake_redis):
    _register_local_batch("empty_batch", [], [])
    catalog_module.resolve_recommendation_batch("tenant_1", 202, "empty_batch", "skipped")
    catalog_module.assert_resource_review_complete("tenant_1", 202)


def test_recommendation_registration_requires_exact_trusted_search(fake_redis):
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="trusted search result",
    ):
        catalog_module.register_recommendation_batch(
            "tenant_1", 202, "forged", [], []
        )

    catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="local_1",
        resource_type="local",
        tool_ids=[1],
        skill_ids=[2],
    )
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="trusted search result",
    ):
        catalog_module.register_recommendation_batch(
            "tenant_1", 202, "local_1", [1, 3], [2]
        )


def test_trusted_search_batch_is_idempotent_but_immutable(fake_redis):
    first = catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="mcp_1",
        resource_type="mcp",
        item_keys=["registry:b", "registry:a"],
    )
    second = catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="mcp_1",
        resource_type="mcp",
        item_keys=["registry:b", "registry:a"],
    )
    assert first == second

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="contents changed",
    ):
        catalog_module._record_trusted_search_batch(
            "tenant_1",
            202,
            recommendation_batch_id="mcp_1",
            resource_type="mcp",
            item_keys=[],
        )


def test_stage_validated_search_batch_is_atomic_with_workflow_stage(fake_redis):
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="requirements_collecting",
    ):
        catalog_module.record_stage_validated_search_batch(
            "tenant_1",
            202,
            recommendation_batch_id="wrong_stage",
            resource_type="local",
        )

    review = catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )
    catalog_module.confirm_requirements_summary(
        "tenant_1", 202, review["fingerprint"]
    )
    catalog_module.set_model_selection_confirmed("tenant_1", 202, True)

    recorded = catalog_module.record_stage_validated_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="local_allowed",
        resource_type="local",
    )
    assert recorded["resource_type"] == "local"

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="local_resource_review",
    ):
        catalog_module.record_stage_validated_search_batch(
            "tenant_1",
            202,
            recommendation_batch_id="online_too_early",
            resource_type="mcp",
        )

    catalog_module.register_recommendation_batch(
        "tenant_1", 202, "local_allowed", [], []
    )
    catalog_module.resolve_recommendation_batch(
        "tenant_1", 202, "local_allowed", "skipped"
    )
    online = catalog_module.record_stage_validated_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="online_allowed",
        resource_type="mcp",
    )
    assert online["resource_type"] == "mcp"

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert "wrong_stage" not in state["trusted_search_batches"]
    assert "online_too_early" not in state["trusted_search_batches"]


def test_identity_confirmation_round_trip(fake_redis):
    assert not catalog_module.get_nl2agent_session_state("tenant_1", 202)["identity_confirmed"]
    catalog_module.confirm_agent_identity("tenant_1", 202)
    assert catalog_module.get_nl2agent_session_state("tenant_1", 202)["identity_confirmed"]


def test_mcp_workflow_blocks_connected_and_resolves_after_binding_or_skip(fake_redis):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        option_id="remote-0",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11, 12],
        bound_tool_ids=[],
    )
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Bind discovered"):
        catalog_module.assert_mcp_workflows_resolved("tenant_1", 202)

    catalog_module.update_mcp_workflow("tenant_1", 202, "registry:github", status="tools_bound", bound_tool_ids=[11])
    catalog_module.assert_mcp_workflows_resolved("tenant_1", 202)
    workflow = catalog_module.get_nl2agent_session_state("tenant_1", 202)["mcp_workflows"]["registry:github"]
    assert "config_values" not in workflow


def test_mcp_bind_and_skip_reservations_are_mutually_exclusive(fake_redis):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11, 12],
        bound_tool_ids=[],
    )

    def reserve_bind():
        return catalog_module.reserve_mcp_binding_operation(
            "tenant_1", 202, 5, "bind-op", [11]
        )

    def reserve_skip():
        return catalog_module.reserve_mcp_binding_operation(
            "tenant_1", 202, 5, "skip-op", []
        )

    successes = []
    failures = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve_bind), executor.submit(reserve_skip)]
        for future in futures:
            try:
                successes.append(future.result())
            except catalog_module.Nl2AgentSessionCatalogError as exc:
                failures.append(exc)

    assert len(successes) == 1
    assert len(failures) == 1
    workflow = catalog_module.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["registry:github"]
    assert workflow["status"] == "binding"
    assert workflow["binding_operation_id"] in {"bind-op", "skip-op"}


def test_mcp_binding_reservation_rejects_tools_not_discovered(fake_redis):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11],
        bound_tool_ids=[],
    )

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="not discovered",
    ):
        catalog_module.reserve_mcp_binding_operation(
            "tenant_1", 202, 5, "bind-op", [12]
        )


def test_completed_mcp_binding_is_idempotent_only_for_its_owner(fake_redis):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11],
        bound_tool_ids=[],
    )
    catalog_module.reserve_mcp_binding_operation(
        "tenant_1", 202, 5, "bind-op", [11]
    )
    catalog_module.complete_mcp_binding_operation(
        "tenant_1", 202, "registry:github", "bind-op", "tools_bound"
    )

    retried = catalog_module.reserve_mcp_binding_operation(
        "tenant_1", 202, 5, "bind-op", [11]
    )
    assert retried["status"] == "tools_bound"
    catalog_module.complete_mcp_binding_operation(
        "tenant_1", 202, "registry:github", "bind-op", "tools_bound"
    )

    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="resolved"):
        catalog_module.reserve_mcp_binding_operation(
            "tenant_1", 202, 5, "other-op", [11]
        )


def test_online_batches_are_idempotent_and_new_batches_reset_confirmation(fake_redis):
    first = _register_online_batch(
        "online_mcp", "mcp", ["registry:b", "registry:a"]
    )
    second = _register_online_batch(
        "online_mcp", "mcp", ["registry:b", "registry:a"]
    )
    assert first == second
    assert first == {
        "resource_type": "mcp",
            "item_keys": ["registry:b", "registry:a"],
        "status": "recommendations_ready",
    }

    _register_online_batch("online_skill", "skill", [])

    assert catalog_module.complete_online_configuration("tenant_1", 202) == [
        "online_mcp",
        "online_skill",
    ]
    catalog_module.assert_online_configuration_complete("tenant_1", 202)

    _register_online_batch("online_skill_new", "skill", ["skill:new"])
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert not state["online_configuration_confirmed"]
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Complete the online"):
        catalog_module.assert_online_configuration_complete("tenant_1", 202)


def test_online_completion_blocks_only_unresolved_mcp_workflows(fake_redis):
    _register_online_batch("online_mcp", "mcp", [])
    _register_online_batch("online_skill", "skill", [])
    catalog_module.update_mcp_workflow("tenant_1", 202, "registry:github", status="connected", mcp_id=5)
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Bind discovered"):
        catalog_module.complete_online_configuration("tenant_1", 202)

    catalog_module.update_mcp_workflow("tenant_1", 202, "registry:github", status="failed")
    catalog_module.complete_online_configuration("tenant_1", 202)


def test_online_completion_blocks_active_skill_installation(fake_redis):
    _prepare_online_review()
    catalog_module.reserve_online_installation(
        "tenant_1", 202, "skill:12", "install-skill:12"
    )

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="Skill installation",
    ):
        catalog_module.complete_online_configuration("tenant_1", 202)

    catalog_module.complete_online_installation(
        "tenant_1",
        202,
        "skill:12",
        "install-skill:12",
        {"skill_id": 12, "installed": True},
    )
    catalog_module.complete_online_configuration("tenant_1", 202)


def test_online_installation_reservation_rejects_another_operation(fake_redis):
    _prepare_online_review()
    catalog_module.reserve_online_installation(
        "tenant_1", 202, "skill:12", "install-skill:12"
    )

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="another operation",
    ):
        catalog_module.reserve_online_installation(
            "tenant_1", 202, "skill:12", "different-operation"
        )


def test_online_completion_requires_both_catalogs(fake_redis):
    _register_online_batch("online_mcp", "mcp", [])

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="both MCP and Skill",
    ):
        catalog_module.complete_online_configuration("tenant_1", 202)

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="both MCP and Skill",
    ):
        catalog_module.assert_online_configuration_complete("tenant_1", 202)


def test_malformed_online_state_is_rejected_with_context(
    fake_redis, caplog, monkeypatch
):
    snapshot = session_store.load_durable_session("tenant_1", 202)
    snapshot["workflow_state"] = {
        "recommendation_batches": {},
        "online_recommendation_batches": {
            "online_bad": {"resource_type": "mcp", "item_keys": "not-a-list"}
        },
    }
    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(return_value=snapshot)
    )

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert "Malformed NL2AGENT session state" in caplog.text


def test_session_state_is_isolated_by_tenant_and_draft(fake_redis, monkeypatch):
    _register_local_batch("batch_1", [1], [])
    primary = session_store.load_durable_session("tenant_1", 202)
    snapshots = {
        ("tenant_1", 202): primary,
        ("tenant_1", 303): {
            **primary,
            "draft_agent_id": 303,
            "workflow_state": catalog_module.initialize_nl2agent_session_state(
                "tenant_1", 303, 903
            ),
        },
        ("tenant_2", 202): {
            **primary,
            "tenant_id": "tenant_2",
            "workflow_state": catalog_module.initialize_nl2agent_session_state(
                "tenant_2", 202, 904
            ),
        },
    }
    monkeypatch.setattr(
        session_store,
        "load_durable_session",
        MagicMock(
            side_effect=lambda tenant, draft: deepcopy(
                snapshots.get((tenant, draft))
            )
        ),
    )
    assert not catalog_module.get_nl2agent_session_state("tenant_1", 303)["recommendation_batches"]
    assert not catalog_module.get_nl2agent_session_state("tenant_2", 202)["recommendation_batches"]


def test_failed_card_delivery_is_idempotent_and_retries_twice(fake_redis):
    first = catalog_module.record_card_delivery(
        "tenant_1",
        202,
        1,
        "local_resources",
        "failed",
        reason="truncated_fence",
    )
    duplicate = catalog_module.record_card_delivery(
        "tenant_1",
        202,
        1,
        "local_resources",
        "failed",
        reason="truncated_fence",
    )
    second = catalog_module.record_card_delivery(
        "tenant_1", 202, 2, "local_resources", "failed", reason="invalid_json"
    )
    third = catalog_module.record_card_delivery(
        "tenant_1",
        202,
        3,
        "local_resources",
        "failed",
        reason="invalid_schema",
    )

    assert first == duplicate
    assert first["retry_count"] == 1
    assert second["retry_count"] == 2
    assert third["retry_count"] == 3


def test_failed_delivery_never_rolls_back_business_state(fake_redis):
    _register_local_batch("pending", [1], [])
    _register_local_batch("applied", [2], [])
    _complete_local_apply("applied", [2], [])

    catalog_module.record_card_delivery(
        "tenant_1",
        202,
        1,
        "local_resources",
        "failed",
        card_key="pending",
        reason="truncated_fence",
    )

    batches = catalog_module.get_nl2agent_session_state("tenant_1", 202)["recommendation_batches"]
    assert batches["pending"]["status"] == "recommendations_ready"
    assert batches["applied"]["status"] == "applied"


def test_rendered_delivery_resets_retry_count(fake_redis):
    catalog_module.record_card_delivery("tenant_1", 202, 1, "model_selection", "failed", reason="invalid_json")
    rendered = catalog_module.record_card_delivery("tenant_1", 202, 2, "model_selection", "rendered")
    assert rendered["retry_count"] == 0
    assert rendered["status"] == "rendered"


def test_requirements_summary_registration_and_button_confirmation(fake_redis):
    summary = {
        "goal": "  Create presentations  ",
        "audience_or_scenario": "Office   users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "No invented facts",
    }

    first = catalog_module.register_requirements_summary("tenant_1", 202, summary)
    second = catalog_module.register_requirements_summary("tenant_1", 202, summary)

    assert first == second
    assert first["status"] == "awaiting_confirmation"
    assert first["is_current"] is True
    assert first["summary"]["goal"] == "Create presentations"
    assert first["summary"]["audience_or_scenario"] == "Office users"
    confirmed = catalog_module.confirm_requirements_summary("tenant_1", 202, first["fingerprint"])
    assert confirmed["status"] == "confirmed"
    assert catalog_module.confirm_requirements_summary("tenant_1", 202, first["fingerprint"])["status"] == "confirmed"
    catalog_module.assert_requirements_confirmed("tenant_1", 202)


def test_changed_requirements_summary_resets_confirmation(fake_redis):
    summary = {
        "goal": "Create presentations",
        "audience_or_scenario": "Office users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "No invented facts",
    }
    catalog_module.register_requirements_summary("tenant_1", 202, summary)
    catalog_module.apply_requirements_revision_text("tenant_1", 202, "change the expected output")
    unchanged = catalog_module.register_requirements_summary("tenant_1", 202, summary)

    assert unchanged["status"] == "collecting"
    assert unchanged["is_current"] is False
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="not awaiting confirmation",
    ):
        catalog_module.confirm_requirements_summary("tenant_1", 202, unchanged["fingerprint"])

    changed = catalog_module.register_requirements_summary(
        "tenant_1", 202, {**summary, "expected_output": "Presentation and notes"}
    )

    assert changed["status"] == "awaiting_confirmation"
    assert changed["is_current"] is True
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="Confirm the requirements summary",
    ):
        catalog_module.assert_requirements_confirmed("tenant_1", 202)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("确认需求", "confirmation_requires_button"),
        ("looks good", "confirmation_requires_button"),
        ("yes", "confirmation_requires_button"),
        ("yes I may have more details later", "ambiguous"),
        ("是 但我还要考虑", "ambiguous"),
        ("确认，但需要修改输出", "modify"),
        ("not correct, change the output", "modify"),
        ("No change, looks good", "confirmation_requires_button"),
        ("无需修改，可以继续", "confirmation_requires_button"),
        ("No change to output; change the audience", "modify"),
        ("无需修改输出，修改受众", "modify"),
        ("我再考虑一下", "ambiguous"),
    ],
)
def test_requirements_message_classifier(text, expected):
    assert catalog_module.classify_requirements_message_intent(text) == expected


def test_requirements_modification_returns_to_collecting(fake_redis):
    catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )

    result = catalog_module.apply_requirements_revision_text("tenant_1", 202, "不正确，改成输出 PDF")

    assert result["intent"] == "modify"
    assert result["status"] == "collecting"


def test_requirements_modification_invalidates_only_summary_delivery(fake_redis):
    catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )
    catalog_module.record_card_delivery(
        "tenant_1", 202, 10, "requirements_summary", "rendered"
    )
    catalog_module.record_card_delivery(
        "tenant_1", 202, 9, "model_selection", "rendered"
    )

    catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "change the expected output"
    )

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert "requirements_summary" not in state["card_delivery"]
    assert state["card_delivery"]["model_selection"]["message_id"] == 9

    catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation and notes",
            "key_constraints": "No invented facts",
        },
    )
    workflow = catalog_module.get_workflow_summary("tenant_1", 202)
    assert workflow["expected_card_types"] == ["requirements_summary"]


@pytest.mark.parametrize("text", ["确认需求", "yes", "可以继续"])
def test_text_confirmation_requires_button(fake_redis, text):
    catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )

    result = catalog_module.apply_requirements_revision_text("tenant_1", 202, text)

    assert result["intent"] == "confirmation_requires_button"
    assert result["status"] == "awaiting_confirmation"


def test_non_revision_text_preserves_requirements_delivery(fake_redis):
    catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )
    catalog_module.record_card_delivery(
        "tenant_1", 202, 10, "requirements_summary", "rendered"
    )

    catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "confirm requirements"
    )

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["card_delivery"]["requirements_summary"]["message_id"] == 10


@pytest.mark.parametrize("text", ["No change, looks good", "无需修改，可以继续"])
def test_negated_modification_keeps_requirements_awaiting_confirmation(
    fake_redis,
    text,
):
    registered = catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )

    result = catalog_module.apply_requirements_revision_text(
        "tenant_1",
        202,
        text,
    )

    assert result["intent"] == "confirmation_requires_button"
    assert result["status"] == "awaiting_confirmation"
    assert result["fingerprint"] == registered["fingerprint"]


def test_stale_requirement_card_cannot_overwrite_or_confirm_current_summary(fake_redis):
    original = {
        "goal": "Create presentations",
        "audience_or_scenario": "Office users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "No invented facts",
    }
    first = catalog_module.register_requirements_summary("tenant_1", 202, original)
    catalog_module.apply_requirements_revision_text("tenant_1", 202, "change the expected output")
    revised = catalog_module.register_requirements_summary(
        "tenant_1", 202, {**original, "expected_output": "Presentation and notes"}
    )

    stale = catalog_module.register_requirements_summary("tenant_1", 202, original)

    assert stale["is_current"] is False
    assert stale["fingerprint"] == revised["fingerprint"]
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="requirements summary is stale",
    ):
        catalog_module.confirm_requirements_summary("tenant_1", 202, first["fingerprint"])


def test_concurrent_online_batch_registration_preserves_both_updates(fake_redis):
    catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="online_mcp",
        resource_type="mcp",
        item_keys=["registry:one"],
    )
    catalog_module._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="online_skill",
        resource_type="skill",
        item_keys=["skill:one"],
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                catalog_module.register_online_recommendation_batch,
                "tenant_1",
                202,
                "online_mcp",
                "mcp",
                ["registry:one"],
            ),
            executor.submit(
                catalog_module.register_online_recommendation_batch,
                "tenant_1",
                202,
                "online_skill",
                "skill",
                ["skill:one"],
            ),
        ]
        for future in futures:
            future.result()

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert set(state["online_recommendation_batches"]) == {
        "online_mcp",
        "online_skill",
    }
    assert state["revision"] == 4


def test_workflow_summary_is_authoritative(fake_redis):
    summary = catalog_module.get_workflow_summary("tenant_1", 202)
    assert summary["current_stage"] == "requirements_collecting"
    assert summary["allowed_actions"] == [
        "clarify_requirements",
        "render_requirements_summary",
    ]

    review = catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )
    summary = catalog_module.get_workflow_summary("tenant_1", 202)
    assert summary["current_stage"] == "requirements_confirmation"
    assert summary["expected_card_types"] == ["requirements_summary"]
    catalog_module.confirm_requirements_summary("tenant_1", 202, review["fingerprint"])
    assert catalog_module.get_workflow_summary("tenant_1", 202)["current_stage"] == "model_selection"


def test_missing_or_old_workflow_state_is_rejected(fake_redis, monkeypatch):
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="missing"):
        catalog_module.get_nl2agent_session_state("tenant_1", 999)

    snapshot = session_store.load_durable_session("tenant_1", 202)
    snapshot["draft_agent_id"] = 303
    snapshot["workflow_state"] = {"schema_version": 1}
    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(return_value=snapshot)
    )
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Malformed"):
        catalog_module.get_nl2agent_session_state("tenant_1", 303)


def test_mcp_installation_lock_is_owned_and_recoverable(fake_redis):
    token = catalog_module.acquire_mcp_installation_lock(
        "tenant_1", 202, "stable-key"
    )
    assert token
    assert (
        catalog_module.acquire_mcp_installation_lock(
            "tenant_1", 202, "stable-key"
        )
        is None
    )

    catalog_module.release_mcp_installation_lock(
        "tenant_1", 202, "stable-key", "wrong-owner"
    )
    assert (
        catalog_module.acquire_mcp_installation_lock(
            "tenant_1", 202, "stable-key"
        )
        is None
    )

    catalog_module.release_mcp_installation_lock(
        "tenant_1", 202, "stable-key", token
    )
    assert catalog_module.acquire_mcp_installation_lock(
        "tenant_1", 202, "stable-key"
    )


def test_revision_routing_preserves_idempotent_final_receipt(fake_redis):
    _prepare_final_review()

    catalog_module.enter_revision_mode("tenant_1", 202)
    summary = catalog_module.get_workflow_summary("tenant_1", 202)

    assert summary["current_stage"] == "revision_routing"
    assert summary["expected_card_types"] == []
    assert "model_selection" in summary["allowed_card_types"]
    assert "select_models" in summary["allowed_actions"]

    catalog_module.record_card_delivery(
        "tenant_1", 202, 71, "final_review", "rendered"
    )
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is True
    assert state["card_delivery"]["final_review"]["message_id"] == 71


def test_model_revision_returns_to_a_fresh_final_review(fake_redis):
    _prepare_final_review()
    catalog_module.enter_revision_mode("tenant_1", 202)
    catalog_module.record_card_delivery(
        "tenant_1", 202, 72, "model_selection", "rendered"
    )

    catalog_module.set_model_selection_confirmed("tenant_1", 202, True)

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    summary = catalog_module.get_workflow_summary("tenant_1", 202)
    assert state["revision_mode"] is False
    assert "final_review" not in state["card_delivery"]
    assert summary["current_stage"] == "final_review"
    assert summary["expected_card_types"] == ["final_review"]


def test_new_final_card_completes_direct_proposal_revision(fake_redis):
    _prepare_final_review()
    catalog_module.enter_revision_mode("tenant_1", 202)

    catalog_module.record_card_delivery(
        "tenant_1", 202, 73, "final_review", "rendered"
    )

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is False
    assert state["card_delivery"]["final_review"]["message_id"] == 73


def test_requirements_revision_reconfirms_without_resetting_other_stages(fake_redis):
    _prepare_final_review()
    catalog_module.enter_revision_mode("tenant_1", 202)
    review = catalog_module.register_requirements_summary(
        "tenant_1",
        202,
        {
            "goal": "Build a revised agent",
            "audience_or_scenario": "Operators",
            "primary_input": "Requests",
            "expected_output": "Actions",
            "key_constraints": "Use trusted resources",
        },
    )

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is True
    assert state["requirements_review"]["status"] == "awaiting_confirmation"

    catalog_module.confirm_requirements_summary(
        "tenant_1", 202, review["fingerprint"]
    )
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is False
    assert state["model_selection_confirmed"] is True
    assert state["identity_confirmed"] is True
    assert "final_review" not in state["card_delivery"]
