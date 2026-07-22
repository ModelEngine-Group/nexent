"""Focused NL2AGENT service tests."""
# ruff: noqa: F405

from test.backend.services.nl2agent_test_support import *  # noqa: F403


@pytest.mark.asyncio
async def test_card_delivery_allows_two_automatic_retries(monkeypatch):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
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
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        lambda message_id, user_id: {
            "message_id": message_id,
            "conversation_id": 902,
            "message_role": "assistant",
            "status": "completed",
        },
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        lambda conversation_id, user_id: (
            test_card_delivery_allows_two_automatic_retries.latest_id
        ),
    )

    results = []
    for index in range(1, 4):
        test_card_delivery_allows_two_automatic_retries.latest_id = index
        results.append(
            await nl2agent_service.report_card_delivery(
                agent_id=202,
                message_id=index,
                card_type="model_selection",
                status="failed",
                card_key=None,
                reason="truncated_fence",
                tenant_id="tenant_1",
                user_id="user_1",
            )
        )

    assert [result["retry_count"] for result in results] == [1, 2, 3]
    assert [result["auto_retry_allowed"] for result in results] == [True, True, False]
    assert all(
        result["chat_injection_text"].startswith("[[NL2AGENT_CARD_RETRY]]")
        for result in results
    )


async def test_card_delivery_accepts_valid_card_in_persisted_message(monkeypatch):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 10,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": (
                    '```nl2agent-model-selection\n{"agent_id": 202}\n```'
                ),
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=10),
    )

    result = await nl2agent_service.report_card_delivery(
        agent_id=202,
        message_id=10,
        card_type="model_selection",
        status="rendered",
        card_key=None,
        reason=None,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["status"] == "rendered"
    assert result["message_id"] == 10


@pytest.mark.asyncio
async def test_revision_routing_accepts_the_targeted_model_card(monkeypatch):
    _confirm_requirements()
    nl2agent_session_catalog.set_model_selection_confirmed("tenant_1", 202, True)
    _register_local_batch("local_empty", [], [])
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "local_empty", "skipped"
    )
    for batch_id, resource_type in (("online_mcp", "mcp"), ("online_skill", "skill")):
        nl2agent_session_catalog._record_trusted_search_batch(
            "tenant_1",
            202,
            recommendation_batch_id=batch_id,
            resource_type=resource_type,
            item_keys=[],
        )
        nl2agent_session_catalog.register_online_recommendation_batch(
            "tenant_1", 202, batch_id, resource_type, []
        )
    nl2agent_session_catalog.complete_online_configuration("tenant_1", 202)
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)
    nl2agent_session_catalog.record_card_delivery(
        "tenant_1", 202, 71, "final_review", "rendered"
    )
    nl2agent_session_catalog.enter_revision_mode("tenant_1", 202)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 72,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": (
                    '```nl2agent-model-selection\n{"agent_id": 202}\n```'
                ),
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=72),
    )

    result = await nl2agent_service.report_card_delivery(
        agent_id=202,
        message_id=72,
        card_type="model_selection",
        status="rendered",
        card_key=None,
        reason=None,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["status"] == "rendered"
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["revision_mode"] is True
    assert state["card_delivery"]["model_selection"]["message_id"] == 72


async def test_requirements_card_delivery_omits_fingerprint_card_key(monkeypatch):
    review = nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )
    message_content = (
        "```nl2agent-requirements-summary\n"
        + json.dumps({"agent_id": 202, **_REQUIREMENTS_SUMMARY})
        + "\n```"
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 10,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": message_content,
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=10),
    )

    first = await nl2agent_service.report_card_delivery(
        agent_id=202,
        message_id=10,
        card_type="requirements_summary",
        status="rendered",
        card_key=None,
        reason=None,
        tenant_id="tenant_1",
        user_id="user_1",
    )
    duplicate = await nl2agent_service.report_card_delivery(
        agent_id=202,
        message_id=10,
        card_type="requirements_summary",
        status="rendered",
        card_key=None,
        reason=None,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert review["fingerprint"]
    assert first == duplicate
    assert first["card_key"] is None
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["card_delivery"]["requirements_summary"]["card_key"] is None


async def test_card_delivery_accepts_valid_card_from_completed_message_units(
    monkeypatch,
):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 10,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": "",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message_units",
        MagicMock(
            return_value=[
                {
                    "unit_type": "final_answer",
                    "unit_status": "completed",
                    "unit_content": "```nl2agent-model-selection\n",
                },
                {
                    "unit_type": "final_answer",
                    "unit_status": "completed",
                    "unit_content": '{"agent_id": 202}\n```',
                },
            ]
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=10),
    )

    result = await nl2agent_service.report_card_delivery(
        agent_id=202,
        message_id=10,
        card_type="model_selection",
        status="rendered",
        card_key=None,
        reason=None,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["status"] == "rendered"
    assert result["message_id"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message_content",
    [
        "The model-selection card is unavailable.",
        "```nl2agent-model-selection\n{broken json}\n```",
        '```nl2agent-model-selection\n{"agent_id": 999}\n```',
    ],
)
async def test_card_delivery_rejects_rendered_receipt_without_valid_card(
    monkeypatch,
    message_content,
    caplog,
):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 10,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": message_content,
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=10),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message_units",
        MagicMock(
            return_value=[
                {
                    "unit_type": "final_answer",
                    "unit_status": "streaming",
                    "unit_content": '```nl2agent-model-selection\n{"agent_id": 202}\n```',
                }
            ]
        ),
    )

    with pytest.raises(
        Nl2AgentStaleCardError,
        match="does not contain",
    ):
        await nl2agent_service.report_card_delivery(
            agent_id=202,
            message_id=10,
            card_type="model_selection",
            status="rendered",
            card_key=None,
            reason=None,
            tenant_id="tenant_1",
            user_id="user_1",
        )

    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert "model_selection" not in state["card_delivery"]
    assert "stale_reason=persisted_card_mismatch" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("first_resource_type", ["mcp", "skill"])
async def test_dual_online_cards_accept_registration_and_receipts_in_either_order(
    monkeypatch,
    first_resource_type,
):
    _confirm_requirements()
    nl2agent_session_catalog.set_model_selection_confirmed("tenant_1", 202, True)
    _register_local_batch("local_empty", [], [])
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "local_empty", "skipped"
    )
    batches = {
        "mcp": ("online_mcp", "web_mcp"),
        "skill": ("online_skill", "web_skill"),
    }
    for resource_type, (batch_id, _card_type) in batches.items():
        nl2agent_session_catalog._record_trusted_search_batch(
            "tenant_1",
            202,
            recommendation_batch_id=batch_id,
            resource_type=resource_type,
            item_keys=[],
        )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 20,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": (
                    "```nl2agent-web-mcps\n"
                    '{"agent_id":202,"recommendation_batch_id":"online_mcp","items":[]}\n'
                    "```\n"
                    "```nl2agent-web-skills\n"
                    '{"agent_id":202,"recommendation_batch_id":"online_skill","items":[]}\n'
                    "```"
                ),
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=20),
    )

    ordered_types = [
        first_resource_type,
        "skill" if first_resource_type == "mcp" else "mcp",
    ]
    for resource_type in ordered_types:
        batch_id, card_type = batches[resource_type]
        await nl2agent_service.register_online_resource_recommendations(
            202, batch_id, resource_type, [], "tenant_1", "user_1"
        )
        await nl2agent_service.report_card_delivery(
            agent_id=202,
            message_id=20,
            card_type=card_type,
            status="rendered",
            card_key=batch_id,
            reason=None,
            tenant_id="tenant_1",
            user_id="user_1",
        )

    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["card_delivery"]["web_mcp"]["status"] == "rendered"
    assert state["card_delivery"]["web_skill"]["status"] == "rendered"


async def test_start_session_returns_builder_draft_and_conversation_ids(monkeypatch):
    clear_nl2agent_session_catalogs()
    db_session, _ = _mock_database_transaction(monkeypatch)
    search_builder = MagicMock(return_value=101)
    search_agent = MagicMock(return_value=_seeded_nl2agent_info())
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(nl2agent_service, "create_conversation", create_conversation)
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_service.start_session(
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
    nl2agent_service.list_all_tools.assert_awaited_once_with(
        tenant_id="tenant_1",
        labels=None,
        limit=2_000,
    )
    nl2agent_service.list_community_mcp_services.assert_awaited_once_with(
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
    clear_nl2agent_session_catalogs()
    _mock_database_transaction(monkeypatch)
    official_skills = [
        {"skill_id": 1, "name": "ready", "status": "installable"},
        {"skill_id": 2, "name": "already-installed", "status": "installed"},
        {"skill_id": 3, "name": "missing-files", "status": "resource_missing"},
    ]
    monkeypatch.setattr(
        nl2agent_service,
        "get_official_skills_with_status",
        MagicMock(return_value=official_skills),
    )
    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", MagicMock(return_value=101)
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_service, "create_agent", MagicMock(return_value={"agent_id": 202})
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    with caplog.at_level("WARNING"):
        await nl2agent_service.start_session(
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
    clear_nl2agent_session_catalogs()
    _, transaction = _mock_database_transaction(monkeypatch)
    create_draft = MagicMock(return_value={"agent_id": 202})
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(return_value=101),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_registry_mcp_services",
        AsyncMock(side_effect=RuntimeError("registry unavailable")),
    )
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(
        nl2agent_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )

    result = await nl2agent_service.start_session(
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
    clear_nl2agent_session_catalogs()
    _, transaction = _mock_database_transaction(monkeypatch)
    transaction.__exit__.side_effect = RuntimeError("commit failed")
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(return_value=101),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_agent",
        MagicMock(return_value={"agent_id": 202}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )

    with pytest.raises(
        Nl2AgentOperationError,
        match="Failed to initialize NL2AGENT session",
    ):
        await nl2agent_service.start_session(
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
    clear_nl2agent_session_catalogs()
    _mock_database_transaction(monkeypatch)
    search_builder = MagicMock(side_effect=ValueError("agent not found"))
    provision_builder = MagicMock(return_value=101)

    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(
        nl2agent_service, "seed_nl2agent_default_agent", provision_builder
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_service, "create_agent", MagicMock(return_value={"agent_id": 202})
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_conversation",
        MagicMock(return_value={"conversation_id": 303}),
    )

    result = await nl2agent_service.start_session(
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
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "seed_nl2agent_default_agent",
        MagicMock(return_value=provisioned_id),
    )
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)

    with pytest.raises(
        Nl2AgentOperationError,
        match="could not be provisioned for this tenant",
    ):
        await nl2agent_service.start_session(
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
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(return_value=101),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value=_seeded_nl2agent_info()),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_or_update_tool_by_tool_info",
        MagicMock(side_effect=RuntimeError("binding failed")),
    )
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)

    with pytest.raises(Nl2AgentOperationError, match="default agent is not ready"):
        await nl2agent_service.start_session(
            user_id="user_1",
            tenant_id="tenant_1",
            language="en",
        )

    create_draft.assert_not_called()


@pytest.mark.asyncio
async def test_start_session_backfills_existing_nl2agent_prompt_template_link(
    monkeypatch,
):
    clear_nl2agent_session_catalogs()
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
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(nl2agent_service, "create_conversation", create_conversation)
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_service.start_session(
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
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)

    result = await nl2agent_service.select_models(
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
    transaction.__exit__.assert_called_once_with(None, None, None)
    assert result["fallback_model_ids"] == [8]
    assert (
        result["chat_injection_text"] == nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT
    )


@pytest.mark.asyncio
async def test_select_models_accepts_legacy_chat_model_type(monkeypatch):
    _confirm_requirements()
    _mock_database_transaction(monkeypatch)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
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
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)

    result = await nl2agent_service.select_models(
        agent_id=202,
        primary_model_id=8,
        fallback_model_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["models"] == [{"model_id": 8, "display_name": "Legacy Chat Model"}]
    assert update_agent.call_args.kwargs["agent_info"].model_ids == [8]


@pytest.mark.asyncio
async def test_select_models_rolls_back_database_when_redis_write_fails(
    monkeypatch,
):
    _confirm_requirements()
    db_session, transaction = _mock_database_transaction(monkeypatch)
    _mock_selectable_models(monkeypatch)
    update_agent = MagicMock()
    set_confirmed = MagicMock(
        side_effect=[
            RuntimeError("Redis unavailable"),
            {"model_selection_confirmed": False},
        ]
    )
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)
    monkeypatch.setattr(
        nl2agent_service,
        "set_model_selection_confirmed",
        set_confirmed,
    )

    with pytest.raises(
        Nl2AgentOperationError,
        match="Failed to save the model selection",
    ) as exc_info:
        await nl2agent_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert update_agent.call_args.kwargs["db_session"] is db_session
    transaction.__exit__.assert_called_once()
    assert transaction.__exit__.call_args.args[0] is RuntimeError
    assert [record.args for record in set_confirmed.call_args_list] == [
        ("tenant_1", 202, True),
        ("tenant_1", 202, False),
    ]


@pytest.mark.asyncio
async def test_select_models_restores_redis_when_database_commit_fails(
    monkeypatch,
):
    _confirm_requirements()
    _, transaction = _mock_database_transaction(monkeypatch)
    transaction.__exit__.side_effect = RuntimeError("database commit failed")
    _mock_selectable_models(monkeypatch)
    monkeypatch.setattr(nl2agent_service, "update_agent", MagicMock())
    set_confirmed = MagicMock()
    monkeypatch.setattr(
        nl2agent_service,
        "set_model_selection_confirmed",
        set_confirmed,
    )

    with pytest.raises(
        Nl2AgentOperationError,
        match="Failed to save the model selection",
    ) as exc_info:
        await nl2agent_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert [record.args for record in set_confirmed.call_args_list] == [
        ("tenant_1", 202, True),
        ("tenant_1", 202, False),
    ]


@pytest.mark.asyncio
async def test_select_models_requires_confirmed_requirements(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )

    with pytest.raises(
        Nl2AgentWorkflowConflictError,
        match="Confirm the requirements summary",
    ):
        await nl2agent_service.select_models(
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
        Nl2AgentFinalizeRequest(
            business_description="Draft a concise brief.",
            duty_prompt="Write the brief.",
            greeting_message="What should I summarize?",
            prompt_template_id=1,
        )


def test_mcp_installation_lock_renews_only_for_its_owner():
    token = nl2agent_session_catalog.acquire_mcp_installation_lock(
        "tenant_1", 202, "install-key"
    )

    assert token
    assert nl2agent_session_catalog.renew_mcp_installation_lock(
        "tenant_1", 202, "install-key", token
    )
    assert not nl2agent_session_catalog.renew_mcp_installation_lock(
        "tenant_1", 202, "install-key", "wrong-token"
    )


def test_mcp_options_share_one_recommendation_installation_lock():
    remote_operation = nl2agent_mcp_service.installation_key(
        202, "registry:github", "remote-0"
    )
    package_operation = nl2agent_mcp_service.installation_key(
        202, "registry:github", "package-0"
    )
    lock_key = nl2agent_mcp_service.installation_lock_key(202, "registry:github")

    assert remote_operation != package_operation
    token = nl2agent_session_catalog.acquire_mcp_installation_lock(
        "tenant_1", 202, lock_key
    )
    assert token
    assert (
        nl2agent_session_catalog.acquire_mcp_installation_lock(
            "tenant_1", 202, lock_key
        )
        is None
    )

    other_lock_key = nl2agent_mcp_service.installation_lock_key(202, "registry:slack")
    assert nl2agent_session_catalog.acquire_mcp_installation_lock(
        "tenant_1", 202, other_lock_key
    )


def test_idempotent_state_mutation_does_not_increment_revision():
    first = nl2agent_session_catalog.record_card_delivery(
        "tenant_1",
        202,
        message_id=10,
        card_type="model_selection",
        status="rendered",
    )
    first_revision = nl2agent_session_catalog.get_nl2agent_session_state(
        "tenant_1", 202
    )["revision"]

    second = nl2agent_session_catalog.record_card_delivery(
        "tenant_1",
        202,
        message_id=10,
        card_type="model_selection",
        status="rendered",
    )

    assert second == first
    assert (
        nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)["revision"]
        == first_revision
    )


@pytest.mark.asyncio
async def test_mcp_installation_stops_when_lock_renewal_is_lost(monkeypatch):
    async def wait_forever(*args, **kwargs):
        await asyncio.Event().wait()

    dependencies = MagicMock()
    dependencies.lock.renew_installation_lock.return_value = False
    monkeypatch.setattr(nl2agent_mcp_service, "_LOCK_HEARTBEAT_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(
        nl2agent_mcp_service,
        "_perform_recommended_mcp_install",
        wait_forever,
    )

    with pytest.raises(nl2agent_service.AgentRunException, match="ownership was lost"):
        await nl2agent_mcp_service._perform_with_lock_heartbeat(
            dependencies,
            agent_id=202,
            recommendation_id="registry:github",
            option_id="remote",
            config_values={},
            tenant_id="tenant_1",
            user_id="user_1",
            stable_key="install-key",
            lock_key="recommendation-lock-key",
            lock_token="token",
        )


@pytest.mark.asyncio
async def test_register_requirements_review_returns_normalized_state(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )

    result = await nl2agent_service.register_requirements_review(
        202,
        {**_REQUIREMENTS_SUMMARY, "goal": "  Build   a document assistant  "},
        "tenant_1",
        "user_1",
    )

    assert result["agent_id"] == 202
    assert result["status"] == "awaiting_confirmation"
    assert result["summary"]["goal"] == "Build a document assistant"
    assert result["fingerprint"]
    assert result["is_current"] is True


@pytest.mark.asyncio
async def test_register_requirements_review_recovers_confirmed_state_without_stage_gate(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    review = nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )
    nl2agent_session_catalog.confirm_requirements_summary(
        "tenant_1", 202, review["fingerprint"]
    )
    revision = nl2agent_session_catalog.get_nl2agent_session_state(
        "tenant_1", 202
    )["revision"]
    monkeypatch.setattr(
        nl2agent_service,
        "_require_workflow_action",
        MagicMock(side_effect=AssertionError("registration must be replayable")),
    )

    result = await nl2agent_service.register_requirements_review(
        202,
        _REQUIREMENTS_SUMMARY,
        "tenant_1",
        "user_1",
    )

    assert result["status"] == "confirmed"
    assert result["is_current"] is True
    assert (
        nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
            "revision"
        ]
        == revision
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_register_online_resources_recovers_batch_without_stage_gate(
    monkeypatch,
    completed,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    if completed:
        _complete_required_online_review()
    else:
        _prepare_required_online_review()
    revision = nl2agent_session_catalog.get_nl2agent_session_state(
        "tenant_1", 202
    )["revision"]
    monkeypatch.setattr(
        nl2agent_service,
        "_require_workflow_action",
        MagicMock(side_effect=AssertionError("registration must be replayable")),
    )

    result = await nl2agent_service.register_online_resource_recommendations(
        202,
        "online_mcp",
        "mcp",
        [],
        "tenant_1",
        "user_1",
    )

    Nl2AgentOnlineRecommendationResponse.model_validate(result)
    assert result["status"] == ("completed" if completed else "recommendations_ready")
    assert (
        nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
            "revision"
        ]
        == revision
    )


@pytest.mark.asyncio
async def test_confirm_requirements_review_returns_auto_continue(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    review = nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )

    result = await nl2agent_service.confirm_requirements_review(
        202, review["fingerprint"], "tenant_1", "user_1"
    )

    assert result == {
        "agent_id": 202,
        "status": "confirmed",
        "fingerprint": review["fingerprint"],
        "chat_injection_text": nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT,
    }


@pytest.mark.asyncio
async def test_confirm_requirements_review_rejects_stale_fingerprint(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )
    nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )

    with pytest.raises(
        nl2agent_session_catalog.Nl2AgentSessionCatalogError,
        match="requirements summary is stale",
    ):
        await nl2agent_service.confirm_requirements_review(
            202, "0" * 64, "tenant_1", "user_1"
        )


def test_process_requirements_revision_text_updates_nl2agent_draft(monkeypatch):
    nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "nl2agent"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )

    result = nl2agent_service.process_requirements_revision_text(
        1, 202, "tenant_1", "user_1", "change the expected output"
    )

    assert result["intent"] == "modify"
    assert result["status"] == "collecting"


@pytest.mark.asyncio
async def test_revised_requirements_card_starts_new_delivery_cycle(monkeypatch):
    nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )
    nl2agent_session_catalog.record_card_delivery(
        "tenant_1", 202, 10, "requirements_summary", "rendered"
    )
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "nl2agent"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )

    nl2agent_service.process_requirements_revision_text(
        1, 202, "tenant_1", "user_1", "change the expected output"
    )
    revised_summary = {
        **_REQUIREMENTS_SUMMARY,
        "expected_output": "A presentation with speaker notes",
    }
    registration = await nl2agent_service.register_requirements_review(
        202, revised_summary, "tenant_1", "user_1"
    )
    message_content = (
        "```nl2agent-requirements-summary\n"
        + json.dumps({"agent_id": 202, **revised_summary})
        + "\n```"
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_message",
        MagicMock(
            return_value={
                "message_id": 11,
                "conversation_id": 902,
                "message_role": "assistant",
                "status": "completed",
                "message_content": message_content,
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_latest_assistant_message_id",
        MagicMock(return_value=11),
    )

    delivery = await nl2agent_service.report_card_delivery(
        agent_id=202,
        message_id=11,
        card_type="requirements_summary",
        status="rendered",
        card_key=None,
        reason=None,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert registration["status"] == "awaiting_confirmation"
    assert registration["is_current"] is True
    assert delivery["message_id"] == 11
    assert delivery["status"] == "rendered"
    state = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)
    assert state["card_delivery"]["requirements_summary"]["message_id"] == 11


def test_process_requirements_revision_ignores_non_nl2agent_runner(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "other_agent"}),
    )

    assert nl2agent_service.process_requirements_revision_text(
        1, 202, "tenant_1", "user_1", "confirm requirements"
    ) == {"intent": "not_applicable"}


def test_process_requirements_revision_ignores_missing_runner(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "find_agent_info_by_agent_id",
        MagicMock(return_value=None),
    )

    assert nl2agent_service.process_requirements_revision_text(
        999, 202, "tenant_1", "user_1", "confirm requirements"
    ) == {"intent": "not_applicable"}


@pytest.mark.asyncio
async def test_select_models_rejects_unavailable_model(monkeypatch):
    _confirm_requirements()
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {"model_id": 7, "model_type": "llm", "connect_status": "unavailable"},
            ]
        ),
    )

    with pytest.raises(
        nl2agent_service.AgentRunException, match="currently unavailable"
    ):
        await nl2agent_service.select_models(
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
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(
            return_value={"agent_id": 202, "name": "draft_test", "created_by": "user_1"}
        ),
    )
    monkeypatch.setattr(
        nl2agent_service, "get_model_records", MagicMock(return_value=records)
    )

    with pytest.raises(nl2agent_service.AgentRunException, match=message):
        await nl2agent_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_draft_without_persisted_primary_model(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
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
        nl2agent_service.AgentRunException, match="Select a primary LLM"
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
        )


@pytest.mark.asyncio
async def test_finalize_revalidates_persisted_model_availability(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
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
        nl2agent_service,
        "get_model_records",
        MagicMock(
            return_value=[
                {"model_id": 7, "model_type": "llm", "connect_status": "unavailable"},
            ]
        ),
    )

    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="Reopen the model-selection card",
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_output_tokens_above_primary_model_capacity(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
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
    update_agent = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)

    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="requested_output_tokens cannot exceed.*1024",
    ):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
            requested_output_tokens=1025,
        )

    update_agent.assert_not_called()
