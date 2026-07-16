import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import fakeredis
import pytest

from agents import nl2agent_session_catalog as catalog_module


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        catalog_module,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=client)),
    )
    catalog_module.initialize_nl2agent_session_state("tenant_1", 202, conversation_id=902)
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
    catalog_module.record_trusted_search_batch(
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


def _register_online_batch(batch_id, resource_type, item_keys):
    catalog_module.record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id=batch_id,
        resource_type=resource_type,
        item_keys=item_keys,
    )
    return catalog_module.register_online_recommendation_batch(
        "tenant_1", 202, batch_id, resource_type, item_keys
    )


def test_catalogs_round_trip_through_shared_redis(fake_redis, monkeypatch):
    catalog_module.set_nl2agent_session_catalogs("tenant_1", 202, _catalogs())

    # A newly created service facade simulates a separate runtime worker while
    # retaining the same shared Redis storage.
    monkeypatch.setattr(
        catalog_module,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=fake_redis)),
    )

    assert catalog_module.get_nl2agent_session_catalogs("tenant_1", 202) == _catalogs()


def test_missing_catalogs_raise_contextual_error(fake_redis, caplog):
    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)

    assert "NL2AGENT catalogs are missing" in caplog.text


def test_malformed_catalogs_raise_contextual_error(fake_redis, caplog):
    key = catalog_module._cache_key("tenant_1", 202)
    fake_redis.set(key, json.dumps({"tool_catalog": "not-a-list"}))

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_catalogs("tenant_1", 202)

    assert "Malformed NL2AGENT catalogs" in caplog.text


def test_recommendation_batch_registration_is_idempotent_and_requires_resolution(
    fake_redis,
):
    first = _register_local_batch("batch_1", [3, 1], [7])
    second = _register_local_batch("batch_1", [1, 3], [7])
    assert first == second
    assert first["status"] == "recommendations_ready"

    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="Apply or skip"):
        catalog_module.assert_resource_review_complete("tenant_1", 202)

    catalog_module.resolve_recommendation_batch("tenant_1", 202, "batch_1", "applied", [1], [7])
    catalog_module.assert_resource_review_complete("tenant_1", 202)


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

    catalog_module.record_trusted_search_batch(
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
    first = catalog_module.record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="mcp_1",
        resource_type="mcp",
        item_keys=["registry:b", "registry:a"],
    )
    second = catalog_module.record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="mcp_1",
        resource_type="mcp",
        item_keys=["registry:a", "registry:b"],
    )
    assert first == second

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="contents changed",
    ):
        catalog_module.record_trusted_search_batch(
            "tenant_1",
            202,
            recommendation_batch_id="mcp_1",
            resource_type="mcp",
            item_keys=[],
        )


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


def test_online_batches_are_idempotent_and_new_batches_reset_confirmation(fake_redis):
    first = _register_online_batch(
        "online_mcp", "mcp", ["registry:b", "registry:a"]
    )
    second = _register_online_batch(
        "online_mcp", "mcp", ["registry:a", "registry:b"]
    )
    assert first == second
    assert first == {
        "resource_type": "mcp",
        "item_keys": ["registry:a", "registry:b"],
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


def test_malformed_online_state_is_rejected_with_context(fake_redis, caplog):
    fake_redis.set(
        catalog_module._state_key("tenant_1", 202),
        json.dumps(
            {
                "recommendation_batches": {},
                "online_recommendation_batches": {"online_bad": {"resource_type": "mcp", "item_keys": "not-a-list"}},
            }
        ),
    )

    with pytest.raises(
        catalog_module.Nl2AgentSessionCatalogError,
        match="tenant=tenant_1, draft_agent_id=202",
    ):
        catalog_module.get_nl2agent_session_state("tenant_1", 202)
    assert "Malformed NL2AGENT session state" in caplog.text


def test_session_state_is_isolated_by_tenant_and_draft(fake_redis):
    _register_local_batch("batch_1", [1], [])
    catalog_module.initialize_nl2agent_session_state("tenant_1", 303, 903)
    catalog_module.initialize_nl2agent_session_state("tenant_2", 202, 904)
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
    catalog_module.resolve_recommendation_batch("tenant_1", 202, "applied", "applied", [2], [])

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
    catalog_module.record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="online_mcp",
        resource_type="mcp",
        item_keys=["registry:one"],
    )
    catalog_module.record_trusted_search_batch(
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


def test_missing_or_old_workflow_state_is_rejected(fake_redis):
    with pytest.raises(catalog_module.Nl2AgentSessionCatalogError, match="missing"):
        catalog_module.get_nl2agent_session_state("tenant_1", 999)

    fake_redis.set(
        catalog_module._state_key("tenant_1", 303),
        json.dumps({"schema_version": 1}),
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
