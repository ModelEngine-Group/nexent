from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from agents import nl2agent_session_catalog as catalog_module
from agents import nl2agent_session_store as session_store


@pytest.fixture
def durable_session(monkeypatch):
    initial_state = catalog_module.initialize_nl2agent_session_state(
        "tenant_1", 202, conversation_id=902
    )
    durable_snapshot = {
        "tenant_id": "tenant_1",
        "user_id": "user_1",
        "runner_agent_id": 101,
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": "active",
        "workflow_revision": 0,
        "workflow_state": initial_state,
        "session_catalogs": _catalogs(),
        "installation_operations": [],
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
        session_store,
        "load_durable_session",
        MagicMock(side_effect=load_durable_session),
    )
    monkeypatch.setattr(
        session_store,
        "persist_workflow_state",
        MagicMock(side_effect=persist_workflow_state),
    )

    def set_session_catalogs(tenant_id, draft_agent_id, catalogs):
        if tenant_id == "tenant_1" and draft_agent_id == 202:
            durable_snapshot["session_catalogs"] = deepcopy(catalogs)

    monkeypatch.setattr(
        catalog_module,
        "set_nl2agent_session_catalogs",
        set_session_catalogs,
        raising=False,
    )

    def list_installation_operations(
        _tenant_id,
        _draft_agent_id,
        *,
        resource_type=None,
        statuses=None,
    ):
        return [
            deepcopy(operation)
            for operation in durable_snapshot["installation_operations"]
            if (resource_type is None or operation["resource_type"] == resource_type)
            and (not statuses or operation["status"] in statuses)
        ]

    monkeypatch.setattr(
        catalog_module,
        "get_nl2agent_installation_operations",
        list_installation_operations,
    )
    return durable_snapshot


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
    return _present_recommendation_batch(batch_id)


def _present_recommendation_batch(batch_id):
    """Set up the state produced by atomic structured-message finalization."""

    def mutate(state):
        batch = state.recommendations[batch_id]
        if batch.status == "searched":
            batch.status = "presented"
        if batch.resource_type in {"mcp", "skill"}:
            state.online_configuration_confirmed = False
        if batch.resource_type == "local":
            return catalog_module._recommendation_batch_response(batch)
        return {
            "resource_type": batch.resource_type,
            "item_keys": list(batch.item_keys),
            "status": (
                "completed" if batch.status == "completed" else "recommendations_ready"
            ),
        }

    return catalog_module._mutate_session_state("tenant_1", 202, mutate)


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
    return _present_recommendation_batch(batch_id)


def _await_requirements_review(summary):
    normalized = {
        key: catalog_module._normalize_requirement_text(summary.get(key))
        for key in catalog_module._REQUIREMENTS_FIELDS
    }
    fingerprint = catalog_module._requirements_fingerprint(normalized)

    def mutate(state):
        state.requirements_review.status = "awaiting_confirmation"
        state.requirements_review.summary = normalized
        state.requirements_review.fingerprint = fingerprint
        return state.requirements_review.model_dump(mode="json")

    return catalog_module._mutate_session_state("tenant_1", 202, mutate)


def _prepare_online_review():
    catalog_module.confirm_requirements_from_summary(
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


def test_catalogs_round_trip_through_authoritative_session(durable_session):
    catalog_module.set_nl2agent_session_catalogs("tenant_1", 202, _catalogs())
    assert catalog_module.get_nl2agent_session_catalogs("tenant_1", 202) == _catalogs()


def test_search_projection_hides_installed_mcp_and_marks_installed_skill(
    durable_session,
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
    }
    durable_session["installation_operations"] = [
        {
            "resource_type": "skill",
            "status": "completed",
            "result": {
                "skill_id": 112,
                "skill_name": "code-review",
            },
        }
    ]

    projected = catalog_module.get_nl2agent_search_catalogs(
        "tenant_1", 202, workflow_state
    )

    assert projected["registry_results"] == []
    assert projected["community_results"] == catalogs["community_results"]
    assert projected["official_skills"][0]["status"] == "installed"
    assert catalog_module.get_nl2agent_session_catalogs("tenant_1", 202) == catalogs


def test_missing_catalogs_raise_contextual_error(durable_session, monkeypatch):
    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(return_value=None)
    )
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)


def test_malformed_catalogs_are_rejected_from_database(durable_session, monkeypatch):
    snapshot = session_store.load_durable_session("tenant_1", 202)
    snapshot["session_catalogs"] = {"tool_catalog": "not-a-list"}
    monkeypatch.setattr(
        session_store, "load_durable_session", MagicMock(return_value=snapshot)
    )

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="field 'tool_catalog' is malformed",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)


def test_recommendation_batch_registration_is_idempotent_and_requires_resolution(
    durable_session,
):
    first = _register_local_batch("batch_1", [3, 1], [7])
    second = _register_local_batch("batch_1", [3, 1], [7])
    assert first == second
    assert first["status"] == "recommendations_ready"

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError, match="Apply or skip"
    ):
        catalog_module.assert_resource_review_complete("tenant_1", 202)

    _complete_local_apply("batch_1", [1], [7])
    catalog_module.assert_resource_review_complete("tenant_1", 202)


def test_local_apply_and_skip_cannot_both_reserve_the_same_batch(durable_session):
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
    assert state["recommendations"]["race"]["status"] in {
        "applying",
        "skipped",
    }


def test_completed_local_apply_is_idempotent_only_for_its_owner(durable_session):
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


def test_empty_recommendation_batch_can_be_explicitly_skipped(durable_session):
    _register_local_batch("empty_batch", [], [])
    catalog_module.resolve_recommendation_batch(
        "tenant_1", 202, "empty_batch", "skipped"
    )
    catalog_module.assert_resource_review_complete("tenant_1", 202)


def test_recommendation_apply_requires_exact_trusted_search(durable_session):
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="not registered",
    ):
        catalog_module.reserve_recommendation_batch_apply(
            "tenant_1", 202, "forged", "forged-op", [], []
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
        match="not part",
    ):
        catalog_module.reserve_recommendation_batch_apply(
            "tenant_1", 202, "local_1", "forged-op", [1, 3], [2]
        )


def test_trusted_search_batch_is_idempotent_but_immutable(durable_session):
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


def test_stage_validated_search_batch_is_atomic_with_workflow_stage(durable_session):
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

    catalog_module.confirm_requirements_from_summary(
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

    _present_recommendation_batch("local_allowed")
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
    assert "wrong_stage" not in state["recommendations"]
    assert "online_too_early" not in state["recommendations"]


def test_identity_confirmation_round_trip(durable_session):
    assert not catalog_module.get_nl2agent_session_state("tenant_1", 202)[
        "identity_confirmed"
    ]
    catalog_module.confirm_agent_identity("tenant_1", 202)
    assert catalog_module.get_nl2agent_session_state("tenant_1", 202)[
        "identity_confirmed"
    ]


def test_mcp_workflow_blocks_connected_and_resolves_after_binding_or_skip(
    durable_session,
):
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
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError, match="Bind discovered"
    ):
        catalog_module.assert_mcp_workflows_resolved("tenant_1", 202)

    catalog_module.update_mcp_workflow(
        "tenant_1", 202, "registry:github", status="tools_bound", bound_tool_ids=[11]
    )
    catalog_module.assert_mcp_workflows_resolved("tenant_1", 202)
    workflow = catalog_module.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["registry:github"]
    assert "config_values" not in workflow


def test_mcp_binding_result_contains_no_workflow_lock_state(durable_session):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11, 12],
        bound_tool_ids=[],
    )

    workflow = catalog_module.complete_mcp_binding_result(
        "tenant_1", 202, 5, [11], "tools_bound"
    )

    assert workflow["status"] == "tools_bound"
    assert workflow["bound_tool_ids"] == [11]
    assert "binding_operation_id" not in workflow


def test_mcp_binding_reservation_rejects_tools_not_discovered(durable_session):
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
        catalog_module.complete_mcp_binding_result(
            "tenant_1", 202, 5, [12], "tools_bound"
        )


def test_completed_mcp_binding_result_is_idempotent_only_for_same_selection(
    durable_session,
):
    catalog_module.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11],
        bound_tool_ids=[],
    )
    catalog_module.complete_mcp_binding_result("tenant_1", 202, 5, [11], "tools_bound")
    retried = catalog_module.complete_mcp_binding_result(
        "tenant_1", 202, 5, [11], "tools_bound"
    )
    assert retried["status"] == "tools_bound"

    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="resolved"):
        catalog_module.complete_mcp_binding_result(
            "tenant_1", 202, 5, [], "binding_skipped"
        )


def test_online_batches_are_idempotent_and_new_batches_reset_confirmation(
    durable_session,
):
    first = _register_online_batch("online_mcp", "mcp", ["registry:b", "registry:a"])
    second = _register_online_batch("online_mcp", "mcp", ["registry:b", "registry:a"])
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
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError, match="Complete the online"
    ):
        catalog_module.assert_online_configuration_complete("tenant_1", 202)


def test_online_completion_blocks_only_unresolved_mcp_workflows(durable_session):
    _register_online_batch("online_mcp", "mcp", [])
    _register_online_batch("online_skill", "skill", [])
    catalog_module.update_mcp_workflow(
        "tenant_1", 202, "registry:github", status="connected", mcp_id=5
    )
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError, match="Bind discovered"
    ):
        catalog_module.complete_online_configuration("tenant_1", 202)

    catalog_module.update_mcp_workflow(
        "tenant_1", 202, "registry:github", status="failed"
    )
    catalog_module.complete_online_configuration("tenant_1", 202)


def test_online_completion_blocks_active_skill_installation(durable_session):
    _prepare_online_review()
    durable_session["installation_operations"] = [
        {
            "resource_type": "skill",
            "status": "running",
            "result": None,
        }
    ]

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="Skill installation",
    ):
        catalog_module.complete_online_configuration("tenant_1", 202)

    durable_session["installation_operations"][0]["status"] = "completed"
    durable_session["installation_operations"][0]["result"] = {
        "skill_id": 12,
        "installed": True,
    }
    catalog_module.complete_online_configuration("tenant_1", 202)


def test_workflow_state_has_no_online_installation_lock_collection(durable_session):
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)

    assert "online_installations" not in state


def test_online_completion_requires_both_catalogs(durable_session):
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
    durable_session, caplog, monkeypatch
):
    snapshot = session_store.load_durable_session("tenant_1", 202)
    snapshot["workflow_state"]["recommendations"] = {
        "online_bad": {
            "resource_type": "mcp",
            "status": "searched",
            "item_keys": "not-a-list",
        }
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


def test_session_state_is_isolated_by_tenant_and_draft(durable_session, monkeypatch):
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
            side_effect=lambda tenant, draft: deepcopy(snapshots.get((tenant, draft)))
        ),
    )
    assert not catalog_module.get_nl2agent_session_state("tenant_1", 303)[
        "recommendations"
    ]
    assert not catalog_module.get_nl2agent_session_state("tenant_2", 202)[
        "recommendations"
    ]


def test_requirements_summary_presentation_and_button_confirmation(durable_session):
    summary = {
        "goal": "  Create presentations  ",
        "audience_or_scenario": "Office   users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "No invented facts",
    }

    first = _await_requirements_review(summary)
    second = _await_requirements_review(summary)

    assert first == second
    assert first["status"] == "awaiting_confirmation"
    assert first["summary"]["goal"] == "Create presentations"
    assert first["summary"]["audience_or_scenario"] == "Office users"
    confirmed = catalog_module.confirm_requirements_summary(
        "tenant_1", 202, first["fingerprint"]
    )
    assert confirmed["status"] == "confirmed"
    assert (
        catalog_module.confirm_requirements_summary(
            "tenant_1", 202, first["fingerprint"]
        )["status"]
        == "confirmed"
    )
    catalog_module.assert_requirements_confirmed("tenant_1", 202)


def test_changed_requirements_summary_requires_a_new_persisted_card(durable_session):
    summary = {
        "goal": "Create presentations",
        "audience_or_scenario": "Office users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "No invented facts",
    }
    original = _await_requirements_review(summary)
    catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "change the expected output"
    )
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="not awaiting confirmation",
    ):
        catalog_module.confirm_requirements_summary(
            "tenant_1", 202, original["fingerprint"]
        )

    changed = _await_requirements_review(
        {**summary, "expected_output": "Presentation and notes"}
    )

    assert changed["status"] == "awaiting_confirmation"
    assert changed["fingerprint"] != original["fingerprint"]
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


def test_requirements_modification_returns_to_collecting(durable_session):
    _await_requirements_review(
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )

    result = catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "不正确，改成输出 PDF"
    )

    assert result["intent"] == "modify"
    assert result["status"] == "collecting"


def test_requirements_modification_preserves_unrelated_business_state(durable_session):
    _await_requirements_review(
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )
    catalog_module.set_model_selection_confirmed("tenant_1", 202, True)

    catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "change the expected output"
    )

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["requirements_review"]["status"] == "collecting"
    assert state["model_selection_confirmed"] is True
    assert "card_delivery" not in state


@pytest.mark.parametrize("text", ["确认需求", "yes", "可以继续"])
def test_text_confirmation_requires_button(durable_session, text):
    _await_requirements_review(
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


def test_non_revision_text_preserves_requirements_review(durable_session):
    registered = _await_requirements_review(
        {
            "goal": "Create presentations",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "No invented facts",
        },
    )
    revision = catalog_module.get_nl2agent_session_state("tenant_1", 202)["revision"]

    result = catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "confirm requirements"
    )

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert result["fingerprint"] == registered["fingerprint"]
    assert state["requirements_review"]["status"] == "awaiting_confirmation"
    assert state["revision"] == revision


@pytest.mark.parametrize("text", ["No change, looks good", "无需修改，可以继续"])
def test_negated_modification_keeps_requirements_awaiting_confirmation(
    durable_session,
    text,
):
    registered = _await_requirements_review(
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


def test_stale_requirement_card_cannot_overwrite_or_confirm_current_summary(
    durable_session,
):
    original = {
        "goal": "Create presentations",
        "audience_or_scenario": "Office users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "No invented facts",
    }
    first = _await_requirements_review(original)
    catalog_module.apply_requirements_revision_text(
        "tenant_1", 202, "change the expected output"
    )
    revised = _await_requirements_review(
        {**original, "expected_output": "Presentation and notes"}
    )
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["requirements_review"]["fingerprint"] == revised["fingerprint"]
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="requirements summary is stale",
    ):
        catalog_module.confirm_requirements_summary(
            "tenant_1", 202, first["fingerprint"]
        )


def test_concurrent_online_batch_registration_preserves_both_updates(durable_session):
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
            executor.submit(_present_recommendation_batch, "online_mcp"),
            executor.submit(_present_recommendation_batch, "online_skill"),
        ]
        for future in futures:
            future.result()

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert {
        key
        for key, batch in state["recommendations"].items()
        if batch["resource_type"] in {"mcp", "skill"}
    } == {
        "online_mcp",
        "online_skill",
    }
    assert state["revision"] == 4


def test_workflow_summary_is_authoritative(durable_session):
    summary = catalog_module.get_workflow_summary("tenant_1", 202)
    assert summary["current_stage"] == "requirements_collecting"
    assert summary["allowed_actions"] == [
        "clarify_requirements",
        "render_requirements_summary",
    ]

    review = _await_requirements_review(
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
    assert summary["expected_card_types"] == []
    catalog_module.confirm_requirements_summary("tenant_1", 202, review["fingerprint"])
    assert (
        catalog_module.get_workflow_summary("tenant_1", 202)["current_stage"]
        == "model_selection"
    )


def test_missing_or_old_workflow_state_is_rejected(durable_session, monkeypatch):
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


def test_revision_routing_has_no_delivery_state(durable_session):
    _prepare_final_review()

    catalog_module.enter_revision_mode("tenant_1", 202)
    summary = catalog_module.get_workflow_summary("tenant_1", 202)

    assert summary["current_stage"] == "revision_routing"
    assert summary["expected_card_types"] == []
    assert "model_selection" in summary["allowed_card_types"]
    assert "select_models" in summary["allowed_actions"]

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is True
    assert "card_delivery" not in state


def test_model_revision_returns_to_a_fresh_final_review(durable_session):
    _prepare_final_review()
    catalog_module.enter_revision_mode("tenant_1", 202)

    catalog_module.set_model_selection_confirmed("tenant_1", 202, True)

    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    summary = catalog_module.get_workflow_summary("tenant_1", 202)
    assert state["revision_mode"] is False
    assert "card_delivery" not in state
    assert summary["current_stage"] == "final_review"
    assert summary["expected_card_types"] == ["final_review"]


def test_requirements_revision_reconfirms_without_resetting_other_stages(
    durable_session,
):
    _prepare_final_review()
    catalog_module.enter_revision_mode("tenant_1", 202)
    review = _await_requirements_review(
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

    catalog_module.confirm_requirements_summary("tenant_1", 202, review["fingerprint"])
    state = catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is False
    assert state["model_selection_confirmed"] is True
    assert state["identity_confirmed"] is True
    assert "card_delivery" not in state
