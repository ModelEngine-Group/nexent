"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

from test.backend.services.nl2agent_test_support import *  # noqa: F403


@pytest.mark.asyncio
async def test_apply_local_resources_batch_binds_tools_and_tenant_skills_atomically(
    monkeypatch,
):
    query_tools = MagicMock(return_value=[{"tool_id": 42, "params": {"path": "/tmp"}}])
    bind_tool = MagicMock()
    query_skills = MagicMock(return_value=[{"skill_id": 7, "name": "writer"}])
    bind_skill = MagicMock()
    db_session, transaction = _mock_database_transaction(monkeypatch)

    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids_for_tenant", query_tools)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(nl2agent_service, "query_skills_by_ids", query_skills)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    monkeypatch.setattr(
        nl2agent_service, "_get_owned_draft", MagicMock(return_value={"agent_id": 202})
    )
    _register_local_batch("batch_1", [42], [7])

    result = await nl2agent_service.apply_local_resources_batch(
        agent_id=202,
        recommendation_batch_id="batch_1",
        tool_ids=[42],
        skill_ids=[7],
        tenant_id="tenant_1",
        user_id="user_1",
    )
    Nl2AgentApplyLocalResourcesResponse.model_validate(result)

    assert result == {
        "recommendation_batch_id": "batch_1",
        "status": "applied",
        "bound_tool_count": 1,
        "bound_skill_count": 1,
        "tool_ids": [42],
        "skill_ids": [7],
        "chat_injection_text": nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT,
    }

    tool_request = bind_tool.call_args.kwargs["tool_info"]
    assert tool_request.tool_id == 42
    assert tool_request.agent_id == 202
    assert tool_request.params == {"path": "/tmp"}
    assert tool_request.enabled is True
    assert bind_tool.call_args.kwargs["db_session"] is db_session
    query_skills.assert_called_once_with([7], "tenant_1")
    bind_tool.assert_called_once()

    skill_request = bind_skill.call_args.kwargs["skill_info"]
    assert skill_request.skill_id == 7
    assert skill_request.agent_id == 202
    assert skill_request.enabled is True
    assert skill_request.version_no == 0
    assert bind_skill.call_args.kwargs["db_session"] is db_session
    bind_skill.assert_called_once()
    query_tools.assert_called_once_with([42], "tenant_1")
    transaction.__enter__.assert_called_once()
    transaction.__exit__.assert_called_once_with(None, None, None)


async def test_register_local_resources_rejects_ids_outside_session_catalog(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1", 202, _EXPECTED_SESSION_CATALOGS
    )
    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="outside this session catalog",
    ):
        await nl2agent_service.register_local_resource_recommendations(
            agent_id=202,
            recommendation_batch_id="forged_batch",
            tool_ids=[999],
            skill_ids=[7],
            tenant_id="tenant_1",
            user_id="user_1",
        )
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert "forged_batch" not in state["recommendation_batches"]


@pytest.mark.asyncio
async def test_register_local_resources_accepts_catalog_subset(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": 1,
                    "params": [
                        {"name": "api_key", "default": "secret-value"},
                        {"name": "limit", "type": "integer", "default": 5},
                    ],
                    "inputs": {
                        "query": {
                            "type": "string",
                            "description": "Runtime-only tool input",
                        }
                    },
                }
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(return_value=[{"skill_id": 7, "name": "brief-writer"}]),
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1", 202, _EXPECTED_SESSION_CATALOGS
    )
    nl2agent_session_catalog._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="trusted_batch",
        resource_type="local",
        tool_ids=[1],
        skill_ids=[7],
    )

    result = await nl2agent_service.register_local_resource_recommendations(
        agent_id=202,
        recommendation_batch_id="trusted_batch",
        tool_ids=[1],
        skill_ids=[7],
        tenant_id="tenant_1",
        user_id="user_1",
    )
    Nl2AgentLocalRecommendationResponse.model_validate(result)

    assert result == {
        "recommendation_batch_id": "trusted_batch",
        "status": "recommendations_ready",
        "tool_ids": [1],
        "skill_ids": [7],
        "applied_tool_ids": [],
        "applied_skill_ids": [],
        "tool_parameter_schemas": {
            "1": [
                {"name": "api_key", "default": None},
                {"name": "limit", "type": "integer", "default": 5},
            ]
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved_status", ["applying", "applied", "skipped"])
async def test_register_local_resources_recovers_resolved_batch_without_stage_gate(
    monkeypatch,
    resolved_status,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    _register_local_batch("recover_batch", [], [])
    if resolved_status == "applying":
        nl2agent_session_catalog.reserve_recommendation_batch_apply(
            "tenant_1", 202, "recover_batch", "pending-operation", [], []
        )
    elif resolved_status == "applied":
        _complete_local_apply("recover_batch", [], [])
    else:
        nl2agent_session_catalog.resolve_recommendation_batch(
            "tenant_1", 202, "recover_batch", "skipped"
        )
    revision = nl2agent_session_catalog.get_nl2agent_session_state(
        "tenant_1", 202
    )["revision"]
    monkeypatch.setattr(
        nl2agent_service,
        "_require_workflow_action",
        MagicMock(side_effect=AssertionError("registration must be replayable")),
    )

    result = await nl2agent_service.register_local_resource_recommendations(
        agent_id=202,
        recommendation_batch_id="recover_batch",
        tool_ids=[],
        skill_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    Nl2AgentLocalRecommendationResponse.model_validate(result)
    assert result["status"] == resolved_status
    assert (
        nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
            "revision"
        ]
        == revision
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing_resource", "error_message"),
    [
        ("tool", "tools that no longer exist"),
        ("skill", "tenant skills that no longer exist"),
    ],
)
async def test_register_local_resources_does_not_advance_state_for_deleted_resources(
    monkeypatch,
    missing_resource,
    error_message,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(return_value=[] if missing_resource == "tool" else [{"tool_id": 1}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(
            return_value=[] if missing_resource == "skill" else [{"skill_id": 7}]
        ),
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1", 202, _EXPECTED_SESSION_CATALOGS
    )
    nl2agent_session_catalog._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id="deleted_resource_batch",
        resource_type="local",
        tool_ids=[1],
        skill_ids=[7],
    )

    with pytest.raises(nl2agent_service.AgentRunException, match=error_message):
        await nl2agent_service.register_local_resource_recommendations(
            agent_id=202,
            recommendation_batch_id="deleted_resource_batch",
            tool_ids=[1],
            skill_ids=[7],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert "deleted_resource_batch" not in state["recommendation_batches"]


@pytest.mark.asyncio
async def test_register_local_resources_rejects_unproven_catalog_batch(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1", 202, _EXPECTED_SESSION_CATALOGS
    )

    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="trusted search result",
    ):
        await nl2agent_service.register_local_resource_recommendations(
            agent_id=202,
            recommendation_batch_id="unproven_batch",
            tool_ids=[1],
            skill_ids=[7],
            tenant_id="tenant_1",
            user_id="user_1",
        )


@pytest.mark.asyncio
async def test_genuine_empty_local_search_can_register_its_trusted_batch(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1", 202, _EXPECTED_SESSION_CATALOGS
    )
    tool = get_search_local_resources_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        tool_catalog=[],
        skill_catalog=[],
        requirements_confirmed=True,
        record_search_result=lambda **result: (
            nl2agent_session_catalog._record_trusted_search_batch(
                "tenant_1", 202, **result
            )
        ),
    )
    payload = json.loads(tool(query="unmatched capability"))

    registered = await nl2agent_service.register_local_resource_recommendations(
        agent_id=202,
        recommendation_batch_id=payload["recommendation_batch_id"],
        tool_ids=[],
        skill_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert registered["status"] == "recommendations_ready"


@pytest.mark.asyncio
async def test_apply_local_resources_batch_uses_catalog_param_defaults(monkeypatch):
    query_tools = MagicMock(
        return_value=[
            {
                "tool_id": 42,
                "params": [
                    {
                        "type": "integer",
                        "name": "top_k",
                        "default": 5,
                        "optional": True,
                    }
                ],
            }
        ]
    )
    bind_tool = MagicMock()
    _mock_database_transaction(monkeypatch)

    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids_for_tenant", query_tools)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(
        nl2agent_service, "_get_owned_draft", MagicMock(return_value={"agent_id": 202})
    )
    _register_local_batch("batch_1", [42], [])

    result = await nl2agent_service.apply_local_resources_batch(
        agent_id=202,
        recommendation_batch_id="batch_1",
        tool_ids=[42],
        skill_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["bound_tool_count"] == 1
    tool_request = bind_tool.call_args.kwargs["tool_info"]
    assert tool_request.params == {"top_k": 5}


@pytest.mark.parametrize(
    ("submitted", "message"),
    [
        ({}, "requires configuration field: endpoint"),
        ({"endpoint": 42}, "endpoint must be string"),
        ({"unknown": "value"}, "unknown configuration fields: unknown"),
    ],
)
def test_resolve_tool_config_values_rejects_invalid_values(submitted, message):
    schema = [
        {
            "name": "endpoint",
            "type": "string",
            "optional": False,
        }
    ]

    with pytest.raises(Nl2AgentValidationError, match=message):
        _resolve_tool_config_values(42, schema, submitted)


def test_resolve_tool_config_values_returns_only_instance_values():
    schema = [
        {"name": "endpoint", "type": "string", "optional": False},
        {"name": "top_k", "type": "integer", "default": 5},
    ]

    assert _resolve_tool_config_values(
        42,
        schema,
        {"endpoint": "https://example.test", "top_k": 8},
    ) == {"endpoint": "https://example.test", "top_k": 8}


def test_resolve_tool_config_values_validates_structured_values_and_choices():
    schema = [
        {"name": "indexes", "type": "array"},
        {"name": "mode", "type": "string", "choices": ["safe", "fast"]},
    ]

    assert _resolve_tool_config_values(
        42, schema, {"indexes": ["docs"], "mode": "safe"}
    ) == {"indexes": ["docs"], "mode": "safe"}
    with pytest.raises(nl2agent_service.AgentRunException, match="declared choice"):
        _resolve_tool_config_values(
            42, schema, {"indexes": ["docs"], "mode": "invalid"}
        )


@pytest.mark.asyncio
async def test_apply_local_resources_batch_rolls_back_every_binding_on_failure(
    monkeypatch,
):
    bind_tool = MagicMock()
    bind_skill = MagicMock(side_effect=RuntimeError("skill write failed"))
    _, transaction = _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(return_value=[{"tool_id": 42, "params": {}}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(return_value=[{"skill_id": 7, "name": "writer"}]),
    )
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    _register_local_batch("batch_1", [42], [7])

    with pytest.raises(
        Nl2AgentOperationError,
        match="no resources were applied",
    ):
        await nl2agent_service.apply_local_resources_batch(
            agent_id=202,
            recommendation_batch_id="batch_1",
            tool_ids=[42],
            skill_ids=[7],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    bind_tool.assert_called_once()
    bind_skill.assert_called_once()
    exit_args = transaction.__exit__.call_args.args
    assert exit_args[0] is RuntimeError
    assert (
        nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
            "recommendation_batches"
        ]["batch_1"]["status"]
        == "recommendations_ready"
    )


@pytest.mark.asyncio
async def test_apply_local_resources_batch_reconciles_after_redis_failure(monkeypatch):
    bind_tool = MagicMock()
    _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(return_value=[{"tool_id": 42, "params": {}}]),
    )
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    _register_local_batch("batch_1", [42], [])
    real_complete = nl2agent_service.complete_recommendation_batch_apply
    attempts = 0

    def flaky_complete(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise nl2agent_session_catalog.Nl2AgentSessionCatalogError(
                "redis unavailable"
            )
        return real_complete(*args, **kwargs)

    monkeypatch.setattr(
        nl2agent_service, "complete_recommendation_batch_apply", flaky_complete
    )

    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="Retry Apply All",
    ):
        await nl2agent_service.apply_local_resources_batch(
            agent_id=202,
            recommendation_batch_id="batch_1",
            tool_ids=[42],
            skill_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    pending = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert pending["recommendation_batches"]["batch_1"]["status"] == "applying"

    result = await nl2agent_service.apply_local_resources_batch(
        agent_id=202,
        recommendation_batch_id="batch_1",
        tool_ids=[42],
        skill_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["status"] == "applied"
    assert (
        result["chat_injection_text"] == nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT
    )
    assert bind_tool.call_count == 2


@pytest.mark.asyncio
async def test_local_apply_different_config_cannot_reuse_pending_operation(
    monkeypatch,
):
    bind_tool = MagicMock()
    _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids_for_tenant",
        MagicMock(
            return_value=[
                {
                    "tool_id": 42,
                    "params": [
                        {"name": "endpoint", "type": "string", "optional": False}
                    ],
                }
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    _register_local_batch("batch_1", [42], [])
    monkeypatch.setattr(
        nl2agent_service,
        "complete_recommendation_batch_apply",
        MagicMock(
            side_effect=nl2agent_session_catalog.Nl2AgentSessionCatalogError(
                "redis unavailable"
            )
        ),
    )

    with pytest.raises(Nl2AgentOperationError, match="Retry Apply All"):
        await nl2agent_service.apply_local_resources_batch(
            agent_id=202,
            recommendation_batch_id="batch_1",
            tool_ids=[42],
            skill_ids=[],
            tool_config_values={42: {"endpoint": "https://first.example"}},
            tenant_id="tenant_1",
            user_id="user_1",
        )

    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="another operation",
    ):
        await nl2agent_service.apply_local_resources_batch(
            agent_id=202,
            recommendation_batch_id="batch_1",
            tool_ids=[42],
            skill_ids=[],
            tool_config_values={42: {"endpoint": "https://second.example"}},
            tenant_id="tenant_1",
            user_id="user_1",
        )

    assert bind_tool.call_count == 1


@pytest.mark.asyncio
async def test_apply_local_resources_batch_rejects_invalid_draft_agent_id(monkeypatch):
    query_tools = MagicMock()
    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids_for_tenant", query_tools)

    with pytest.raises(nl2agent_service.AgentRunException):
        await nl2agent_service.apply_local_resources_batch(
            agent_id=0,
            recommendation_batch_id="batch_1",
            tool_ids=[42],
            skill_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    query_tools.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_agent_rejects_invalid_draft_agent_id(monkeypatch):
    update_agent = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)

    with pytest.raises(nl2agent_service.AgentRunException):
        await nl2agent_service.finalize_agent(
            agent_id=0,
            user_id="user_1",
            tenant_id="tenant_1",
            business_description="Build a helper agent",
        )

    update_agent.assert_not_called()


def test_finalize_request_rejects_fabricated_persisted_fields():
    with pytest.raises(ValidationError):
        Nl2AgentFinalizeRequest(
            business_description="Build document presentations",
            duty_prompt="Create presentations from documents.",
            greeting_message="Upload a document to begin.",
            name="invented_name",
            model_ids=[999],
            tool_ids=[999],
            skill_ids=[888],
        )


def test_finalize_request_rejects_unknown_verification_fields():
    with pytest.raises(ValidationError):
        Nl2AgentFinalizeRequest(
            business_description="Build document presentations",
            duty_prompt="Create presentations from documents.",
            greeting_message="Upload a document to begin.",
            verification_config={"enabled": False, "mode": "basic"},
        )


def test_finalize_request_rejects_more_than_six_example_questions():
    with pytest.raises(ValidationError):
        Nl2AgentFinalizeRequest(
            business_description="Build document presentations",
            duty_prompt="Create presentations from documents.",
            greeting_message="Upload a document to begin.",
            example_questions=[str(index) for index in range(7)],
        )
