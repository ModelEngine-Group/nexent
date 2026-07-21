"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

from consts.exceptions import Nl2AgentDraftNotFoundError
from test.backend.services.nl2agent_test_support import *  # noqa: F403


@pytest.mark.asyncio
async def test_finalize_uses_persisted_resources(monkeypatch):
    draft = {
        "agent_id": 202,
        "name": "draft_test",
        "created_by": "user_1",
        "display_name": "Old title",
        "business_logic_model_id": 7,
        "model_ids": [7],
    }
    monkeypatch.setattr(
        nl2agent_service, "search_agent_info_by_agent_id", MagicMock(return_value=draft)
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                    "max_output_tokens": 1024,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "find_agent_id_by_agent_name", MagicMock(return_value=None)
    )
    update = MagicMock()
    bind_tool = MagicMock()
    bind_skill = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(return_value=[{"tool_id": 42, "params": {"saved": True}}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[{"skill_id": 7, "config_values": {"saved": True}}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": 42,
                    "origin_name": "Document Parser",
                    "source": "local",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(
            return_value=[
                {
                    "skill_id": 7,
                    "name": "Presentation Builder",
                    "source": "custom",
                }
            ]
        ),
    )
    _register_local_batch("batch_1", [42], [7])
    _complete_local_apply("batch_1", [42], [7])
    _complete_required_online_review()
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)

    result = await nl2agent_service.finalize_agent(
        agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        business_description="Build document presentations",
        duty_prompt="Create presentations from documents.",
        greeting_message="Upload a document to begin.",
        requested_output_tokens=1024,
    )
    Nl2AgentFinalizeResponse.model_validate(result)

    assert result["name"] == "old_title"
    assert result["display_name"] == "Old title"
    assert result["tool_ids"] == [42]
    assert result["skill_ids"] == [7]
    assert update.call_args.kwargs["agent_info"].requested_output_tokens == 1024
    bind_tool.assert_not_called()
    bind_skill.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_rejects_dangling_resources_before_updating_draft(monkeypatch):
    draft = {
        "agent_id": 202,
        "name": "draft_test",
        "created_by": "user_1",
        "display_name": "Document Helper",
        "business_logic_model_id": 7,
        "model_ids": [7],
    }
    monkeypatch.setattr(
        nl2agent_service, "search_agent_info_by_agent_id", MagicMock(return_value=draft)
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(return_value=[{"tool_id": 404}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(return_value=[]),
    )
    update = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    _register_local_batch("batch_1", [404], [])
    _complete_local_apply("batch_1", [404], [])
    _complete_required_online_review()
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)

    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="tool 404.*Reconfigure the draft",
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
            business_description="Build document presentations",
            duty_prompt="Create presentations from documents.",
            greeting_message="Upload a document to begin.",
        )

    update.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_rejects_incomplete_generated_proposal(monkeypatch):
    draft = {
        "agent_id": 202,
        "name": "draft_test",
        "created_by": "user_1",
        "display_name": "Document Helper",
        "business_logic_model_id": 7,
        "model_ids": [7],
    }
    monkeypatch.setattr(
        nl2agent_service, "search_agent_info_by_agent_id", MagicMock(return_value=draft)
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                }
            ]
        ),
    )
    _register_local_batch("batch_1", [], [])
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "skipped"
    )
    _complete_required_online_review()
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)

    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="business_description, duty_prompt, greeting_message",
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_connected_mcp_until_tools_are_bound_or_skipped(
    monkeypatch,
):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
                "display_name": "Document Helper",
                "business_logic_model_id": 7,
                "model_ids": [7],
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                },
            ]
        ),
    )
    _register_local_batch("batch_1", [], [])
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "skipped"
    )
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)
    nl2agent_session_catalog.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        option_id="remote-0",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[11],
        bound_tool_ids=[],
    )

    with pytest.raises(
        Nl2AgentWorkflowConflictError,
        match="Bind discovered MCP tools",
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
            business_description="Build document presentations",
            duty_prompt="Create presentations from documents.",
            greeting_message="Upload a document to begin.",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("registered_resource_type", ["mcp", "skill"])
async def test_finalize_requires_both_online_catalogs(
    monkeypatch, registered_resource_type
):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
                "display_name": "Document Helper",
                "business_logic_model_id": 7,
                "model_ids": [7],
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                }
            ]
        ),
    )
    _register_local_batch("batch_1", [], [])
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "skipped"
    )
    nl2agent_session_catalog._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id=f"online_{registered_resource_type}",
        resource_type=registered_resource_type,
        item_keys=[],
    )
    nl2agent_session_catalog.register_online_recommendation_batch(
        "tenant_1",
        202,
        f"online_{registered_resource_type}",
        registered_resource_type,
        [],
    )
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)

    with pytest.raises(
        Nl2AgentWorkflowConflictError,
        match="both MCP and Skill",
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
            business_description="Build document presentations",
            duty_prompt="Create presentations from documents.",
            greeting_message="Upload a document to begin.",
        )


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("Customer Support", "customer_support"),
        ("!!!", "agent_202"),
        ("文档助手", "agent_202"),
        ("123 helper", "agent_202"),
    ],
)
def test_generate_internal_agent_name(display_name, expected, monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(return_value=None),
    )
    assert (
        nl2agent_service._generate_internal_agent_name(display_name, 202, "tenant_1")
        == expected
    )


def test_generate_internal_agent_name_appends_agent_id_for_duplicate(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service, "find_agent_id_by_agent_name", MagicMock(return_value=99)
    )
    assert (
        nl2agent_service._generate_internal_agent_name(
            "Customer Support", 202, "tenant_1"
        )
        == "customer_support_202"
    )


def test_generate_internal_agent_name_preserves_unexpected_database_error(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        nl2agent_service._generate_internal_agent_name(
            "Customer Support", 202, "tenant_1"
        )


def test_generate_internal_agent_name_preserves_unexpected_value_error(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("invalid query")),
    )
    with pytest.raises(ValueError, match="invalid query"):
        nl2agent_service._generate_internal_agent_name(
            "Customer Support", 202, "tenant_1"
        )


@pytest.mark.asyncio
async def test_save_agent_identity_persists_display_name_and_confirmation(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    db_session, transaction = _mock_database_transaction(monkeypatch)
    update = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(return_value=None),
    )

    result = await nl2agent_service.save_agent_identity(
        202, "  Document Helper  ", "tenant_1", "user_1"
    )

    assert result == {
        "agent_id": 202,
        "display_name": "Document Helper",
        "internal_name": "document_helper",
        "identity_confirmed": True,
        "chat_injection_text": nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT,
    }
    assert update.call_args.kwargs["agent_info"].display_name == "Document Helper"
    assert update.call_args.kwargs["db_session"] is db_session
    transaction.__exit__.assert_called_once_with(None, None, None)
    assert nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
        "identity_confirmed"
    ]


@pytest.mark.asyncio
async def test_save_agent_identity_retries_confirmation_after_redis_failure(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            side_effect=[
                {"agent_id": 202, "name": "draft_test", "created_by": "user_1"},
                {
                    "agent_id": 202,
                    "name": "draft_test",
                    "display_name": "Document Helper",
                    "created_by": "user_1",
                },
            ]
        ),
    )
    _mock_database_transaction(monkeypatch)
    update = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(return_value=None),
    )
    real_confirm = nl2agent_service.confirm_agent_identity
    attempts = 0

    def flaky_confirm(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Redis unavailable")
        return real_confirm(*args, **kwargs)

    monkeypatch.setattr(
        nl2agent_service,
        "confirm_agent_identity",
        flaky_confirm,
    )

    with pytest.raises(
        Nl2AgentOperationError,
        match="display name was saved.*Retry saving",
    ):
        await nl2agent_service.save_agent_identity(
            202,
            "Document Helper",
            "tenant_1",
            "user_1",
        )

    assert update.called
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["identity_confirmed"] is False

    result = await nl2agent_service.save_agent_identity(
        202,
        "Document Helper",
        "tenant_1",
        "user_1",
    )

    assert result["identity_confirmed"] is True
    assert update.call_count == 1
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["identity_confirmed"] is True


@pytest.mark.asyncio
async def test_save_agent_identity_does_not_confirm_when_database_commit_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
            }
        ),
    )
    _, transaction = _mock_database_transaction(monkeypatch)
    transaction.__exit__.side_effect = RuntimeError("commit failed")
    confirm = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", MagicMock())
    monkeypatch.setattr(nl2agent_service, "confirm_agent_identity", confirm)

    with pytest.raises(
        Nl2AgentOperationError,
        match="Failed to save the agent display name",
    ):
        await nl2agent_service.save_agent_identity(
            202,
            "Document Helper",
            "tenant_1",
            "user_1",
        )

    confirm.assert_not_called()
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["identity_confirmed"] is False


@pytest.mark.asyncio
async def test_save_agent_identity_rejects_whitespace(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    with pytest.raises(nl2agent_service.AgentRunException, match="cannot be empty"):
        await nl2agent_service.save_agent_identity(202, "   ", "tenant_1", "user_1")


@pytest.mark.asyncio
async def test_online_recommendation_registration_and_completion(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )

    nl2agent_session_catalog._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="online_1",
        resource_type="skill",
        item_keys=["skill:7"],
    )
    registered = await nl2agent_service.register_online_resource_recommendations(
        202, "online_1", "skill", ["skill:7"], "tenant_1", "user_1"
    )
    assert registered["status"] == "recommendations_ready"
    nl2agent_session_catalog._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="online_mcp",
        resource_type="mcp",
        item_keys=[],
    )
    mcp_registered = await nl2agent_service.register_online_resource_recommendations(
        202, "online_mcp", "mcp", [], "tenant_1", "user_1"
    )
    assert mcp_registered["status"] == "recommendations_ready"

    completed = await nl2agent_service.confirm_online_resource_configuration(
        202, "tenant_1", "user_1"
    )
    assert completed == {
        "agent_id": 202,
        "online_configuration_confirmed": True,
        "completed_batch_ids": ["online_1", "online_mcp"],
        "chat_injection_text": nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT,
    }


@pytest.mark.asyncio
async def test_online_recommendation_rejects_unproven_empty_batch(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )

    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="trusted search result",
    ):
        await nl2agent_service.register_online_resource_recommendations(
            202, "forged_empty", "mcp", [], "tenant_1", "user_1"
        )


@pytest.mark.asyncio
async def test_local_skip_returns_automatic_continuation_text(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    _register_local_batch("local_empty", [], [])

    result = await nl2agent_service.skip_local_resource_recommendations(
        202, "local_empty", "tenant_1", "user_1"
    )

    assert result["status"] == "skipped"
    assert (
        result["chat_injection_text"] == nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT
    )


@pytest.mark.asyncio
async def test_get_session_state_returns_generated_name_when_candidate_is_available(
    monkeypatch,
):
    session_state_reader = MagicMock(
        side_effect=nl2agent_session_catalog.get_nl2agent_session_state
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_session_state",
        session_state_reader,
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_readable_draft_reader",
        lambda _user_id: MagicMock(
            return_value=(
                {
                    "agent_id": 202,
                    "display_name": "Customer Support",
                    "business_logic_model_id": 7,
                    "model_ids": [7],
                },
                "completed",
            )
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                }
            ]
        ),
    )
    _register_local_batch("batch_in_progress", [], [])
    nl2agent_session_catalog.reserve_recommendation_batch_apply(
        "tenant_1", 202, "batch_in_progress", "local-operation", [], []
    )
    nl2agent_session_catalog.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:github",
        status="connected",
        mcp_id=5,
        discovered_tool_ids=[],
        bound_tool_ids=[],
    )
    nl2agent_session_catalog.reserve_mcp_binding_operation(
        "tenant_1", 202, 5, "mcp-operation", []
    )

    result = await nl2agent_service.get_session_state(202, "tenant_1", "user_1")
    Nl2AgentSessionStateResponse.model_validate(result)

    assert result["agent_id"] == 202
    assert result["session_status"] == "completed"
    assert result["expected_card_types"] == []
    assert result["allowed_actions"] == []
    assert result["internal_name"] == "customer_support"
    assert result["business_logic_model_id"] == 7
    assert result["model_ids"] == [7]
    assert result["models"] == [
        {
            "model_id": 7,
            "display_name": "Primary LLM",
            "role": "primary",
            "valid": True,
        }
    ]
    assert result["invalid_references"] == []
    session_state_reader.assert_called_once_with("tenant_1", 202)
    public_batch = result["resource_review"]["recommendation_batches"][
        "batch_in_progress"
    ]
    assert public_batch["status"] == "recommendations_ready"
    assert "operation_id" not in public_batch
    public_workflow = result["resource_review"]["mcp_workflows"]["registry:github"]
    assert public_workflow["status"] == "connected"
    assert "binding_operation_id" not in public_workflow
    assert "online_installations" not in result["resource_review"]


@pytest.mark.asyncio
async def test_get_session_state_resolves_names_and_resource_origins(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_readable_draft_reader",
        lambda _user_id: MagicMock(
            return_value=(
                {
                    "agent_id": 202,
                    "display_name": "Document Assistant",
                    "business_logic_model_id": 7,
                    "model_ids": [7, 8],
                },
                "active",
            )
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary LLM",
                },
                {
                    "model_id": 8,
                    "model_type": "chat",
                    "connect_status": "available",
                    "model_name": "Fallback LLM",
                },
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(
            return_value=[
                {
                    "tool_id": 11,
                    "params": {"api_key": "never-return-this", "limit": 20},
                },
                {"tool_id": 12},
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": 11,
                    "origin_name": "Local Reader",
                    "source": "local",
                    "params": [
                        {"name": "api_key", "isSecret": True},
                        {"name": "limit", "type": "integer", "default": 10},
                    ],
                },
                {"tool_id": 12, "name": "Web Fetch", "source": "mcp"},
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[{"skill_id": 21}, {"skill_id": 22}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(
            return_value=[
                {"skill_id": 21, "name": "Local Skill", "source": "custom"},
                {"skill_id": 22, "name": "Official Skill", "source": "official"},
            ]
        ),
    )
    _prepare_required_online_review()
    _register_local_batch("restore_batch", [11], [])
    _complete_local_apply("restore_batch", [11], [])
    nl2agent_session_catalog.update_mcp_workflow(
        "tenant_1",
        202,
        "registry:web-fetch",
        status="tools_bound",
        bound_tool_ids=[12],
    )
    reservation = nl2agent_session_catalog.reserve_online_installation(
        "tenant_1", 202, "skill:official", "install-skill:official"
    )
    nl2agent_session_catalog.complete_online_installation(
        "tenant_1",
        202,
        "skill:official",
        reservation["operation_id"],
        {"skill_id": 22, "skill_name": "Official Skill"},
    )

    result = await nl2agent_service.get_session_state(202, "tenant_1", "user_1")

    assert [model["display_name"] for model in result["models"]] == [
        "Primary LLM",
        "Fallback LLM",
    ]
    assert [model["role"] for model in result["models"]] == ["primary", "fallback"]
    assert [(tool["name"], tool["origin"]) for tool in result["tools"]] == [
        ("Local Reader", "local"),
        ("Web Fetch", "online"),
    ]
    assert [(skill["name"], skill["origin"]) for skill in result["skills"]] == [
        ("Local Skill", "local"),
        ("Official Skill", "online"),
    ]
    local_reader = result["tools"][0]
    assert local_reader["configuration"]["api_key"] == {
        "value": None,
        "configured": True,
        "secret": True,
    }
    assert local_reader["configuration"]["limit"]["value"] == 20
    assert result["local_tool_parameter_schemas"]["restore_batch"]["11"] == [
        {"name": "api_key", "isSecret": True, "default": None},
        {"name": "limit", "type": "integer", "default": 10},
    ]
    assert "never-return-this" not in str(result)
    assert result["invalid_references"] == []


@pytest.mark.asyncio
async def test_get_session_state_reports_invalid_persisted_references(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_readable_draft_reader",
        lambda _user_id: MagicMock(
            return_value=(
                {
                    "agent_id": 202,
                    "display_name": "Document Assistant",
                    "business_logic_model_id": 7,
                    "model_ids": [7],
                },
                "active",
            )
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_id_by_agent_name",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        nl2agent_service, "get_model_records", MagicMock(return_value=[])
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(return_value=[{"tool_id": 11}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[{"skill_id": 21}]),
    )
    monkeypatch.setattr(
        nl2agent_service, "query_skills_by_ids", MagicMock(return_value=[])
    )

    result = await nl2agent_service.get_session_state(202, "tenant_1", "user_1")

    assert result["tools"] == []
    assert result["skills"] == []
    assert result["invalid_references"] == [
        {"reference_type": "model", "reference_id": 7, "reason": "not_found"},
        {"reference_type": "tool", "reference_id": 11, "reason": "not_found"},
        {"reference_type": "skill", "reference_id": 21, "reason": "not_found"},
    ]


def test_resume_session_validates_draft_and_conversation_before_reactivation(
    monkeypatch,
):
    session = {
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": "completed",
    }
    readable = MagicMock(return_value=session)
    draft = MagicMock(return_value={"agent_id": 202})
    conversation = MagicMock(return_value={"conversation_id": 902})
    resume = MagicMock(return_value={**session, "status": "active"})
    monkeypatch.setattr(nl2agent_service, "require_readable_session", readable)
    monkeypatch.setattr(nl2agent_service, "_get_draft_configuration", draft)
    monkeypatch.setattr(nl2agent_service, "get_conversation", conversation)
    monkeypatch.setattr(nl2agent_service, "resume_session_lifecycle", resume)

    result = nl2agent_service.resume_session(202, "tenant_1", "user_1")

    assert result["status"] == "active"
    draft.assert_called_once_with(202, "tenant_1")
    conversation.assert_called_once_with(902, user_id="user_1")
    resume.assert_called_once_with(
        draft_agent_id=202,
        tenant_id="tenant_1",
        user_id="user_1",
    )


def test_resume_session_rejects_missing_conversation(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "require_readable_session",
        MagicMock(
            return_value={
                "draft_agent_id": 202,
                "conversation_id": 902,
                "status": "completed",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_draft_configuration",
        MagicMock(return_value={"agent_id": 202}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_conversation",
        MagicMock(return_value=None),
    )
    resume = MagicMock()
    monkeypatch.setattr(nl2agent_service, "resume_session_lifecycle", resume)

    with pytest.raises(Nl2AgentDraftNotFoundError):
        nl2agent_service.resume_session(202, "tenant_1", "user_1")

    resume.assert_not_called()


def test_resume_session_maps_missing_draft_to_not_found(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "require_readable_session",
        MagicMock(
            return_value={
                "draft_agent_id": 202,
                "conversation_id": 902,
                "status": "completed",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_draft_configuration",
        MagicMock(side_effect=Nl2AgentOperationError("missing draft")),
    )

    with pytest.raises(Nl2AgentDraftNotFoundError):
        nl2agent_service.resume_session(202, "tenant_1", "user_1")


def test_completed_state_reader_maps_missing_draft_to_not_found(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "require_readable_session",
        MagicMock(return_value={"status": "completed"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_draft_configuration",
        MagicMock(side_effect=Nl2AgentOperationError("missing draft")),
    )

    reader = nl2agent_service._readable_draft_reader("user_1")

    with pytest.raises(Nl2AgentDraftNotFoundError):
        reader(202, "tenant_1")


def test_seed_nl2agent_default_agent_sets_prompt_and_available_models(monkeypatch):
    seed_tools = MagicMock(return_value=[11, 12])
    query_agents = MagicMock(return_value=[])
    create_agent = MagicMock(return_value={"agent_id": 101})
    bind_tool = MagicMock()
    get_models = MagicMock(
        return_value=[
            {"model_id": 7, "model_type": "llm", "connect_status": "available"},
            {"model_id": 8, "model_type": "chat", "connect_status": "available"},
            {"model_id": 9, "model_type": "embedding", "connect_status": "available"},
            {"model_id": 10, "model_type": "llm", "connect_status": "unavailable"},
        ]
    )

    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_builtin_tools", seed_tools)
    monkeypatch.setattr(
        nl2agent_service, "query_all_agent_info_by_tenant_id", query_agents
    )
    monkeypatch.setattr(nl2agent_service, "create_agent", create_agent)
    monkeypatch.setattr(nl2agent_service, "get_model_records", get_models)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )

    result = nl2agent_service.seed_nl2agent_default_agent(
        tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 101
    payload = create_agent.call_args.args[0]
    assert payload["name"] == "nl2agent"
    assert payload["display_name"] == "Agent Builder"
    assert payload["description"] == "NL2AGENT public description"
    assert payload["business_description"] == "NL2AGENT business description"
    assert payload["prompt_template_id"] is None
    assert payload["prompt_template_name"] is None
    assert payload["duty_prompt"] == "NL2AGENT concise duty"
    assert payload["duty_prompt"] != "NL2AGENT full runtime system prompt"
    assert payload["constraint_prompt"] == "NL2AGENT concise constraint"
    assert payload["few_shots_prompt"] == ""
    assert payload["verification_config"]["enabled"] is True
    assert payload["verification_config"]["final_verification_enabled"] is True
    assert payload["verification_config"]["llm_verification_enabled"] is False
    assert payload["model_ids"] == [7, 8]
    assert payload["business_logic_model_id"] == 7


def test_seed_nl2agent_default_agent_backfills_existing_seed_defaults(
    monkeypatch,
):
    seed_tools = MagicMock(return_value=[11, 12])
    query_agents = MagicMock(
        return_value=[
            {
                "agent_id": 101,
                "name": "nl2agent",
                "display_name": "Old Builder",
                "description": "Old description",
                "business_description": "Old business description",
                "prompt_template_id": None,
                "prompt_template_name": None,
                "duty_prompt": "placeholder prompt",
                "constraint_prompt": "placeholder constraint",
                "few_shots_prompt": "placeholder few shots",
                "verification_config": None,
                "model_ids": [],
                "business_logic_model_id": None,
            }
        ]
    )
    update_agent = MagicMock()
    create_agent = MagicMock()
    get_models = MagicMock(
        return_value=[
            {"model_id": 7, "model_type": "llm", "connect_status": "available"},
            {"model_id": 8, "model_type": "chat", "connect_status": "available"},
        ]
    )

    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_builtin_tools", seed_tools)
    monkeypatch.setattr(
        nl2agent_service, "query_all_agent_info_by_tenant_id", query_agents
    )
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_agent)
    monkeypatch.setattr(nl2agent_service, "get_model_records", get_models)

    result = nl2agent_service.seed_nl2agent_default_agent(
        tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 101
    create_agent.assert_not_called()
    request = update_agent.call_args.kwargs["agent_info"]
    assert request.display_name == "Agent Builder"
    assert request.description == "NL2AGENT public description"
    assert request.business_description == "NL2AGENT business description"
    assert request.prompt_template_id is None
    assert request.prompt_template_name is None
    assert request.duty_prompt == "NL2AGENT concise duty"
    assert request.duty_prompt != "NL2AGENT full runtime system prompt"
    assert request.constraint_prompt == "NL2AGENT concise constraint"
    assert request.few_shots_prompt == ""
    assert request.verification_config["enabled"] is True
    assert request.verification_config["final_verification_enabled"] is True
    assert request.verification_config["llm_verification_enabled"] is False
    assert request.model_ids == [7, 8]
    assert request.business_logic_model_id == 7
    update_agent.assert_called_once_with(
        agent_id=101,
        agent_info=request,
        user_id="user_1",
        version_no=0,
    )
