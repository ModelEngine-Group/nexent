"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

from test.backend.services.nl2agent_test_support import *  # noqa: F403


async def test_start_session_returns_builder_draft_and_conversation_ids(monkeypatch):
    db_session, _ = _mock_database_transaction(monkeypatch)
    search_builder = MagicMock(return_value=101)
    search_agent = MagicMock(return_value=_seeded_nl2agent_info())
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_runtime_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_runtime_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_runtime_service, "create_agent", create_draft)
    monkeypatch.setattr(nl2agent_runtime_service, "create_conversation", create_conversation)
    monkeypatch.setattr(
        nl2agent_runtime_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_runtime_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )
    Nl2AgentSessionStartResponse.model_validate(result)

    assert result == {
        "nl2agent_agent_id": 101,
        "draft_agent_id": 202,
        "conversation_id": 303,
        "draft_name": "draft_abcdef12",
    }
    assert get_nl2agent_session_catalogs("tenant_1", 202) == _EXPECTED_SESSION_CATALOGS
    assert result["draft_agent_id"] != result["nl2agent_agent_id"]

    search_builder.assert_called_once_with("nl2agent", "tenant_1")
    search_agent.assert_called_once_with(agent_id=101, tenant_id="tenant_1")
    nl2agent_runtime_service.list_all_tools.assert_awaited_once_with(
        tenant_id="tenant_1",
        labels=None,
        limit=2_000,
    )
    nl2agent_runtime_service.list_community_mcp_services.assert_awaited_once_with(
        search=None,
        cursor=None,
        limit=100,
    )
    draft_payload = create_draft.call_args.args[0]
    assert draft_payload["name"] == "draft_abcdef12"
    assert draft_payload["name"].startswith("draft_")
    create_draft.assert_called_once_with(
        draft_payload,
        tenant_id="tenant_1",
        user_id="user_1",
        db_session=db_session,
    )
    create_conversation.assert_called_once_with(
        conversation_title="NL2AGENT - draft_abcdef12",
        user_id="user_1",
        agent_id=101,
        db_session=db_session,
    )


@pytest.mark.asyncio
async def test_start_session_keeps_installable_and_recoverable_official_skills(
    monkeypatch, caplog
):
    _mock_database_transaction(monkeypatch)
    official_skills = [
        {"skill_id": 1, "name": "ready", "status": "installable"},
        {"skill_id": 2, "name": "already-installed", "status": "installed"},
        {"skill_id": 3, "name": "missing-files", "status": "resource_missing"},
    ]
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "get_official_skills_with_status",
        MagicMock(return_value=official_skills),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service, "search_agent_id_by_agent_name", MagicMock(return_value=101)
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service, "create_agent", MagicMock(return_value={"agent_id": 202})
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    with caplog.at_level("WARNING"):
        await nl2agent_runtime_service.start_session(
            user_id="user_1",
            tenant_id="tenant_1",
            language="en",
        )

    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        official_skills[0],
        official_skills[2],
    ]
    assert "tenant_id=tenant_1" in caplog.text
    assert "draft_agent_id=202" in caplog.text
    assert "missing-files" in caplog.text
    assert "online recoverable" in caplog.text


@pytest.mark.asyncio
async def test_start_session_degrades_when_registry_catalog_is_unavailable(
    monkeypatch,
):
    _, transaction = _mock_database_transaction(monkeypatch)
    create_draft = MagicMock(return_value={"agent_id": 202})
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_id_by_agent_name",
        MagicMock(return_value=101),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "list_registry_mcp_services",
        AsyncMock(side_effect=RuntimeError("registry unavailable")),
    )
    monkeypatch.setattr(nl2agent_runtime_service, "create_agent", create_draft)
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )

    result = await nl2agent_runtime_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result["draft_agent_id"] == 202
    assert get_nl2agent_session_catalogs("tenant_1", 202)["registry_results"] == []
    create_draft.assert_called_once()
    transaction.__enter__.assert_called_once()


@pytest.mark.asyncio
async def test_start_session_does_not_expose_state_when_database_commit_fails(
    monkeypatch,
):
    _, transaction = _mock_database_transaction(monkeypatch)
    transaction.__exit__.side_effect = RuntimeError("commit failed")
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_id_by_agent_name",
        MagicMock(return_value=101),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "create_agent",
        MagicMock(return_value={"agent_id": 202}),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )

    with pytest.raises(
        Nl2AgentOperationError,
        match="Failed to initialize NL2AGENT session",
    ):
        await nl2agent_runtime_service.start_session(
            user_id="user_1", tenant_id="tenant_1", language="en"
        )

    monkeypatch.setattr(
        nl2agent_session_store,
        "load_durable_session",
        MagicMock(return_value=None),
    )
    with pytest.raises(nl2agent_session_catalog.Nl2AgentSessionCatalogError):
        get_nl2agent_session_catalogs("tenant_1", 202)
    with pytest.raises(nl2agent_session_catalog.Nl2AgentSessionCatalogError):
        nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)


@pytest.mark.asyncio
async def test_start_session_provisions_builder_for_existing_tenant_when_missing(
    monkeypatch,
):
    _mock_database_transaction(monkeypatch)
    search_builder = MagicMock(side_effect=ValueError("agent not found"))
    provision_builder = MagicMock(return_value=101)

    monkeypatch.setattr(
        nl2agent_runtime_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(
        nl2agent_runtime_service, "seed_nl2agent_default_agent", provision_builder
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service, "create_agent", MagicMock(return_value={"agent_id": 202})
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )

    result = await nl2agent_runtime_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result["nl2agent_agent_id"] == 101
    search_builder.assert_called_once_with("nl2agent", "tenant_1")
    provision_builder.assert_called_once_with(
        tenant_id="tenant_1",
        user_id="user_1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provisioned_id", [None, 0, -1, True])
async def test_start_session_fails_before_draft_creation_when_provisioning_fails(
    monkeypatch,
    provisioned_id,
):
    create_draft = MagicMock()
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "seed_nl2agent_default_agent",
        MagicMock(return_value=provisioned_id),
    )
    monkeypatch.setattr(nl2agent_runtime_service, "create_agent", create_draft)

    with pytest.raises(
        Nl2AgentOperationError,
        match="could not be provisioned for this tenant",
    ):
        await nl2agent_runtime_service.start_session(
            user_id="user_1",
            tenant_id="tenant_1",
            language="en",
        )

    create_draft.assert_not_called()


@pytest.mark.asyncio
async def test_start_session_fails_before_draft_creation_when_builder_is_incomplete(
    monkeypatch,
):
    create_draft = MagicMock()
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_id_by_agent_name",
        MagicMock(return_value=101),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "create_or_update_tool_by_tool_info",
        MagicMock(side_effect=RuntimeError("binding failed")),
    )
    monkeypatch.setattr(nl2agent_runtime_service, "create_agent", create_draft)

    with pytest.raises(Nl2AgentOperationError, match="default agent is not ready"):
        await nl2agent_runtime_service.start_session(
            user_id="user_1",
            tenant_id="tenant_1",
            language="en",
        )

    create_draft.assert_not_called()


@pytest.mark.asyncio
async def test_start_session_backfills_existing_nl2agent_prompt_template_link(
    monkeypatch,
):
    _mock_database_transaction(monkeypatch)
    search_builder = MagicMock(return_value=101)
    search_agent = MagicMock(
        return_value={
            "agent_id": 101,
            "prompt_template_id": None,
            "prompt_template_name": None,
        }
    )
    update_agent = MagicMock()
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_runtime_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_runtime_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_runtime_service, "update_agent", update_agent)
    monkeypatch.setattr(nl2agent_runtime_service, "create_agent", create_draft)
    monkeypatch.setattr(nl2agent_runtime_service, "create_conversation", create_conversation)
    monkeypatch.setattr(
        nl2agent_runtime_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_runtime_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result["nl2agent_agent_id"] == 101
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
    update_agent.assert_called_once_with(
        agent_id=101,
        agent_info=request,
        user_id="user_1",
        version_no=0,
    )


@pytest.mark.asyncio
async def test_select_models_persists_primary_and_ordered_fallbacks(monkeypatch):
    _confirm_requirements()
    db_session, transaction = _mock_database_transaction(monkeypatch)
    _mock_selectable_models(monkeypatch)
    update_agent = MagicMock()
    set_confirmed = MagicMock(return_value={"model_selection_confirmed": True})
    monkeypatch.setattr(nl2agent_runtime_service, "update_agent", update_agent)
    monkeypatch.setattr(
        nl2agent_runtime_service, "set_model_selection_confirmed", set_confirmed
    )

    result = await nl2agent_runtime_service.select_models(
        agent_id=202,
        primary_model_id=7,
        fallback_model_ids=[8],
        tenant_id="tenant_1",
        user_id="user_1",
    )
    Nl2AgentModelSelectionResponse.model_validate(result)

    request = update_agent.call_args.kwargs["agent_info"]
    assert request.business_logic_model_id == 7
    assert request.model_ids == [7, 8]
    assert update_agent.call_args.kwargs["db_session"] is db_session
    set_confirmed.assert_called_once_with(
        "tenant_1", 202, True, db_session=db_session
    )
    transaction.__exit__.assert_called_once_with(None, None, None)
    assert result["fallback_model_ids"] == [8]
    assert "chat_injection_text" not in result


@pytest.mark.asyncio
async def test_select_models_accepts_legacy_chat_model_type(monkeypatch):
    _confirm_requirements()
    _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {
                    "model_id": 8,
                    "model_type": "chat",
                    "connect_status": "available",
                    "display_name": "Legacy Chat Model",
                }
            ]
        ),
    )
    update_agent = MagicMock()
    monkeypatch.setattr(nl2agent_runtime_service, "update_agent", update_agent)

    result = await nl2agent_runtime_service.select_models(
        agent_id=202,
        primary_model_id=8,
        fallback_model_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["models"] == [{"model_id": 8, "display_name": "Legacy Chat Model"}]
    assert update_agent.call_args.kwargs["agent_info"].model_ids == [8]


@pytest.mark.asyncio
async def test_select_models_requires_confirmed_requirements(monkeypatch):
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )

    with pytest.raises(
        Nl2AgentWorkflowConflictError,
        match="Confirm the requirements summary",
    ):
        await nl2agent_runtime_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )


def test_workflow_action_gate_rejects_completed_stage_actions():
    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="select_models.*requirements_collecting",
    ):
        nl2agent_session_catalog.assert_workflow_action_allowed(
            "tenant_1", 202, "select_models"
        )

    _confirm_requirements()
    assert (
        nl2agent_session_catalog.assert_workflow_action_allowed(
            "tenant_1", 202, "select_models"
        )["current_stage"]
        == "model_selection"
    )
    nl2agent_session_catalog.set_model_selection_confirmed("tenant_1", 202, True)

    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="select_models.*local_resource_search",
    ):
        nl2agent_session_catalog.assert_workflow_action_allowed(
            "tenant_1", 202, "select_models"
        )


def test_finalize_request_rejects_model_supplied_prompt_template_id():
    with pytest.raises(ValidationError, match="prompt_template_id"):
        Nl2AgentFinalizeActionPayload(
            business_description="Draft a concise brief.",
            duty_prompt="Write the brief.",
            greeting_message="What should I summarize?",
            prompt_template_id=1,
        )


def test_process_requirements_revision_text_updates_nl2agent_draft(monkeypatch):
    _await_requirements_review()
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "nl2agent"}),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )

    result = nl2agent_runtime_service.process_requirements_revision_text(
        1, 202, "tenant_1", "user_1", "change the expected output"
    )

    assert result["intent"] == "modify"
    assert result["status"] == "collecting"


def test_process_requirements_revision_ignores_non_nl2agent_runner(monkeypatch):
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "other_agent"}),
    )

    assert nl2agent_runtime_service.process_requirements_revision_text(
        1, 202, "tenant_1", "user_1", "confirm requirements"
    ) == {"intent": "not_applicable"}


def test_process_requirements_revision_ignores_missing_runner(monkeypatch):
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value=None),
    )

    assert nl2agent_runtime_service.process_requirements_revision_text(
        999, 202, "tenant_1", "user_1", "confirm requirements"
    ) == {"intent": "not_applicable"}


@pytest.mark.asyncio
async def test_select_models_rejects_unavailable_model(monkeypatch):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {"model_id": 7, "model_type": "llm", "connect_status": "unavailable"},
            ]
        ),
    )

    with pytest.raises(
        nl2agent_runtime_service.AgentRunException, match="currently unavailable"
    ):
        await nl2agent_runtime_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([], "does not exist"),
        (
            [{"model_id": 7, "model_type": "embedding", "connect_status": "available"}],
            "not an LLM",
        ),
    ],
)
async def test_select_models_rejects_non_platform_llms(monkeypatch, records, message):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service, "get_model_records", MagicMock(return_value=records)
    )

    with pytest.raises(nl2agent_runtime_service.AgentRunException, match=message):
        await nl2agent_runtime_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_draft_without_persisted_primary_model(monkeypatch):
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
                "model_ids": [],
            }
        ),
    )

    with pytest.raises(
        nl2agent_runtime_service.AgentRunException, match="Select a primary LLM"
    ):
        await nl2agent_runtime_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
        )


@pytest.mark.asyncio
async def test_finalize_revalidates_persisted_model_availability(monkeypatch):
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
                "business_logic_model_id": 7,
                "model_ids": [7],
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {"model_id": 7, "model_type": "llm", "connect_status": "unavailable"},
            ]
        ),
    )

    with pytest.raises(
        nl2agent_runtime_service.AgentRunException,
        match="Reopen the model-selection card",
    ):
        await nl2agent_runtime_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_output_tokens_above_primary_model_capacity(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_runtime_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={
                "agent_id": 202,
                "name": "draft_test",
                "created_by": "user_1",
                "business_logic_model_id": 7,
                "model_ids": [7],
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_runtime_service,
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
    update_agent = MagicMock()
    monkeypatch.setattr(nl2agent_runtime_service, "update_agent", update_agent)

    with pytest.raises(
        nl2agent_runtime_service.AgentRunException,
        match="requested_output_tokens cannot exceed.*1024",
    ):
        await nl2agent_runtime_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
            requested_output_tokens=1025,
        )

    update_agent.assert_not_called()
