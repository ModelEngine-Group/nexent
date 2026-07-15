"""Unit tests for NL2AGENT service orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents import nl2agent_session_catalog
from agents.nl2agent_session_catalog import (
    clear_nl2agent_session_catalogs,
    get_nl2agent_session_catalogs,
)
from services import nl2agent_service


class _FixedUuid:
    hex = "abcdef1234567890"


_RAW_TOOL_ROWS = [
    {
        "tool_id": 1,
        "name": "local_search",
        "description": "Search local documents",
        "labels": ["search"],
        "source": "local",
        "category": "retrieval",
        "usage": "local_search",
        "params": [{"name": "query", "type": "string"}],
    },
    {
        "tool_id": 2,
        "name": "remote_only",
        "description": "Remote tool should not be injected",
        "source": "remote",
    },
]
_EXPECTED_TOOL_CATALOG = [
    {
        "tool_id": 1,
        "name": "local_search",
        "description": "Search local documents",
        "labels": ["search"],
        "source": "local",
        "category": "retrieval",
        "usage": "local_search",
        "params": [{"name": "query", "type": "string"}],
    }
]
_RAW_SKILL_ROWS = [
    {
        "skill_id": 7,
        "name": "brief-writer",
        "description": "Write short research briefs",
        "tags": ["writing"],
        "config_schema": {"tone": {"type": "string"}},
    }
]
_EXPECTED_SKILL_CATALOG = [
    {
        "skill_id": 7,
        "name": "brief-writer",
        "description": "Write short research briefs",
        "tags": ["writing"],
        "config_schema": {"tone": {"type": "string"}},
    }
]
_REGISTRY_RESULTS = [{"name": "github-mcp", "description": "Repository automation"}]
_COMMUNITY_RESULTS = [{"communityId": 55, "name": "browser-mcp"}]
_OFFICIAL_SKILLS = [
    {
        "skill_id": 12,
        "skill_name": "code-review",
        "name": "code-review",
        "description": "Review source changes.",
        "tags": ["code", "review"],
        "source": "official",
        "status": "installable",
    }
]
_EXPECTED_SESSION_CATALOGS = {
    "tool_catalog": _EXPECTED_TOOL_CATALOG,
    "skill_catalog": _EXPECTED_SKILL_CATALOG,
    "registry_results": _REGISTRY_RESULTS,
    "community_results": _COMMUNITY_RESULTS,
    "official_skills": _OFFICIAL_SKILLS,
}

_REQUIREMENTS_SUMMARY = {
    "goal": "Build a document assistant",
    "audience_or_scenario": "Office users preparing reports",
    "primary_input": "Business documents",
    "expected_output": "A presentation",
    "key_constraints": "Preserve source facts",
}


def _confirm_requirements(tenant_id="tenant_1", draft_agent_id=202):
    review = nl2agent_session_catalog.register_requirements_summary(
        tenant_id, draft_agent_id, _REQUIREMENTS_SUMMARY
    )
    nl2agent_session_catalog.confirm_requirements_summary(
        tenant_id, draft_agent_id, review["fingerprint"]
    )


def _complete_required_online_review(tenant_id="tenant_1", draft_agent_id=202):
    _confirm_requirements(tenant_id, draft_agent_id)
    nl2agent_session_catalog.register_online_recommendation_batch(
        tenant_id, draft_agent_id, "online_mcp", "mcp", []
    )
    nl2agent_session_catalog.register_online_recommendation_batch(
        tenant_id, draft_agent_id, "online_skill", "skill", []
    )
    nl2agent_session_catalog.complete_online_configuration(
        tenant_id, draft_agent_id
    )


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def setex(self, key, ttl, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def scan_iter(self, match):
        prefix = match.removesuffix("*")
        return (key for key in list(self.data) if key.startswith(prefix))

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)


@pytest.fixture(autouse=True)
def mock_nl2agent_seed_defaults(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        nl2agent_session_catalog,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=fake_redis)),
    )
    clear_nl2agent_session_catalogs()
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_seed_config",
        MagicMock(
            return_value={
                "agent_info": {
                    "name": "nl2agent",
                    "display_name": "Agent Builder",
                    "description": "NL2AGENT public description",
                    "business_description": "NL2AGENT business description",
                },
                "prompt_segments": {
                    "duty_prompt": "NL2AGENT concise duty",
                    "constraint_prompt": "NL2AGENT concise constraint",
                    "few_shots_prompt": "",
                },
                "system_prompt": "NL2AGENT full runtime system prompt",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_all_tools",
        MagicMock(return_value=_RAW_TOOL_ROWS),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_tenant_skills",
        MagicMock(return_value=_RAW_SKILL_ROWS),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_registry_mcp_services",
        AsyncMock(return_value={"servers": _REGISTRY_RESULTS}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_community_mcp_services",
        MagicMock(return_value={"items": _COMMUNITY_RESULTS}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_official_skills_with_status",
        MagicMock(return_value=_OFFICIAL_SKILLS),
    )
    yield
    clear_nl2agent_session_catalogs()


def _seeded_nl2agent_info(agent_id: int = 101):
    return {
        "agent_id": agent_id,
        "name": "nl2agent",
        "display_name": "Agent Builder",
        "description": "NL2AGENT public description",
        "business_description": "NL2AGENT business description",
        "prompt_template_id": None,
        "prompt_template_name": None,
        "duty_prompt": "NL2AGENT concise duty",
        "constraint_prompt": "NL2AGENT concise constraint",
        "few_shots_prompt": "",
        "verification_config": nl2agent_service._NL2AGENT_VERIFICATION_CONFIG,
        "model_ids": [],
    }


def test_marketplace_metadata_redaction_removes_declared_and_container_secrets():
    sanitized = nl2agent_service._redact_mcp_marketplace_metadata({
        "headers": [{
            "name": "Authorization", "isSecret": True, "value": "registry-secret",
        }],
        "configJson": {
            "mcpServers": {
                "example": {
                    "command": "npx",
                    "env": {"API_TOKEN": "community-secret", "REGION": "eu"},
                }
            }
        },
    })

    assert sanitized["headers"][0]["value"] is None
    environment = sanitized["configJson"]["mcpServers"]["example"]["env"]
    assert environment == {"API_TOKEN": None, "REGION": "eu"}


@pytest.mark.asyncio
async def test_start_session_returns_builder_draft_and_conversation_ids(monkeypatch):
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

    assert result == {
        "nl2agent_agent_id": 101,
        "draft_agent_id": 202,
        "conversation_id": 303,
        "draft_name": "draft_abcdef12",
        **_EXPECTED_SESSION_CATALOGS,
    }
    assert get_nl2agent_session_catalogs("tenant_1", 202) == _EXPECTED_SESSION_CATALOGS
    assert result["draft_agent_id"] != result["nl2agent_agent_id"]

    search_builder.assert_called_once_with("nl2agent", "tenant_1")
    search_agent.assert_called_once_with(agent_id=101, tenant_id="tenant_1")
    draft_payload = create_draft.call_args.args[0]
    assert draft_payload["name"] == "draft_abcdef12"
    assert draft_payload["name"].startswith("draft_")
    create_draft.assert_called_once_with(
        draft_payload, tenant_id="tenant_1", user_id="user_1"
    )
    create_conversation.assert_called_once_with(
        conversation_title="NL2AGENT - draft_abcdef12", user_id="user_1"
    )


@pytest.mark.asyncio
async def test_start_session_keeps_only_installable_official_skills(
    monkeypatch, caplog
):
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
        result = await nl2agent_service.start_session(
            user_id="user_1", tenant_id="tenant_1", language="en"
        )

    assert result["official_skills"] == [official_skills[0]]
    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        official_skills[0]
    ]
    assert "tenant_id=tenant_1" in caplog.text
    assert "draft_agent_id=202" in caplog.text
    assert "missing-files" in caplog.text


@pytest.mark.asyncio
async def test_start_session_seeds_nl2agent_for_current_tenant_when_missing(
    monkeypatch,
):
    search_builder = MagicMock(side_effect=Exception("agent not found"))
    seed_builder = MagicMock(return_value=101)
    search_agent = MagicMock(return_value=_seeded_nl2agent_info())
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_default_agent", seed_builder)
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(nl2agent_service, "create_conversation", create_conversation)
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result["nl2agent_agent_id"] == 101
    assert result["draft_agent_id"] == 202
    search_builder.assert_called_once_with("nl2agent", "tenant_1")
    seed_builder.assert_called_once_with(tenant_id="tenant_1", user_id="user_1")
    search_agent.assert_called_once_with(agent_id=101, tenant_id="tenant_1")
    draft_payload = create_draft.call_args.args[0]
    assert draft_payload["name"] == "draft_abcdef12"


@pytest.mark.asyncio
async def test_start_session_backfills_existing_nl2agent_prompt_template_link(
    monkeypatch,
):
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
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_model_records", MagicMock(return_value=[
        {"model_id": 7, "model_type": "llm", "connect_status": "available", "display_name": "Primary"},
        {"model_id": 8, "model_type": "llm", "connect_status": "available", "display_name": "Fallback"},
    ]))
    update_agent = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)

    result = await nl2agent_service.select_models(
        agent_id=202, primary_model_id=7, fallback_model_ids=[8],
        tenant_id="tenant_1", user_id="user_1",
    )

    request = update_agent.call_args.kwargs["agent_info"]
    assert request.business_logic_model_id == 7
    assert request.model_ids == [7, 8]
    assert result["fallback_model_ids"] == [8]
    assert (
        result["chat_injection_text"]
        == nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT
    )


@pytest.mark.asyncio
async def test_select_models_requires_confirmed_requirements(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )

    with pytest.raises(
        nl2agent_service.AgentRunException,
        match="Confirm the requirements summary",
    ):
        await nl2agent_service.select_models(
            agent_id=202,
            primary_model_id=7,
            fallback_model_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
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
    )

    assert result["agent_id"] == 202
    assert result["status"] == "awaiting_confirmation"
    assert result["summary"]["goal"] == "Build a document assistant"
    assert result["fingerprint"]
    assert result["is_current"] is True


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
        202, review["fingerprint"], "tenant_1"
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
            202, "0" * 64, "tenant_1"
        )


def test_process_requirements_revision_text_updates_nl2agent_draft(monkeypatch):
    nl2agent_session_catalog.register_requirements_summary(
        "tenant_1", 202, _REQUIREMENTS_SUMMARY
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "nl2agent"}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202}),
    )

    result = nl2agent_service.process_requirements_revision_text(
        1, 202, "tenant_1", "change the expected output"
    )

    assert result["intent"] == "modify"
    assert result["status"] == "collecting"


def test_process_requirements_revision_ignores_non_nl2agent_runner(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 1, "name": "other_agent"}),
    )

    assert nl2agent_service.process_requirements_revision_text(
        1, 202, "tenant_1", "confirm requirements"
    ) == {"intent": "not_applicable"}


@pytest.mark.asyncio
async def test_select_models_rejects_unavailable_model(monkeypatch):
    _confirm_requirements()
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_model_records", MagicMock(return_value=[
        {"model_id": 7, "model_type": "llm", "connect_status": "unavailable"},
    ]))

    with pytest.raises(nl2agent_service.AgentRunException, match="currently unavailable"):
        await nl2agent_service.select_models(
            agent_id=202, primary_model_id=7, fallback_model_ids=[],
            tenant_id="tenant_1", user_id="user_1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([], "does not exist"),
        ([{"model_id": 7, "model_type": "embedding", "connect_status": "available"}], "not an LLM"),
    ],
)
async def test_select_models_rejects_non_platform_llms(monkeypatch, records, message):
    _confirm_requirements()
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_model_records", MagicMock(return_value=records))

    with pytest.raises(nl2agent_service.AgentRunException, match=message):
        await nl2agent_service.select_models(
            agent_id=202, primary_model_id=7, fallback_model_ids=[],
            tenant_id="tenant_1", user_id="user_1",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_draft_without_persisted_primary_model(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test", "model_ids": []}
    ))

    with pytest.raises(nl2agent_service.AgentRunException, match="Select a primary LLM"):
        await nl2agent_service.finalize_agent(
            agent_id=202,
            user_id="user_1",
            tenant_id="tenant_1",
        )


@pytest.mark.asyncio
async def test_finalize_revalidates_persisted_model_availability(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={
            "agent_id": 202,
            "name": "draft_test",
            "business_logic_model_id": 7,
            "model_ids": [7],
        }
    ))
    monkeypatch.setattr(nl2agent_service, "get_model_records", MagicMock(return_value=[
        {"model_id": 7, "model_type": "llm", "connect_status": "unavailable"},
    ]))

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
async def test_bind_mcp_tools_validates_provenance_and_binds(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_mcp_record_by_id_and_tenant", MagicMock(
        return_value={"mcp_id": 5, "mcp_name": "github"}
    ))
    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", MagicMock(return_value=[
        {"tool_id": 11, "author": "tenant_1", "source": "mcp", "usage": "github"},
    ]))
    bind = MagicMock()
    monkeypatch.setattr(nl2agent_service, "create_or_update_tool_by_tool_info", bind)
    monkeypatch.setattr(
        nl2agent_service,
        "find_mcp_workflow_by_id",
        MagicMock(return_value=("registry:github", {"status": "connected"})),
    )
    update_workflow = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_mcp_workflow", update_workflow)

    result = await nl2agent_service.bind_mcp_tools(
        agent_id=202, mcp_id=5, tool_ids=[11], tenant_id="tenant_1", user_id="user_1"
    )

    assert result["bound_tool_ids"] == [11]
    assert bind.call_count == 1
    update_workflow.assert_called_once_with(
        "tenant_1",
        202,
        "registry:github",
        status="tools_bound",
        bound_tool_ids=[11],
    )


@pytest.mark.asyncio
async def test_skip_mcp_tool_binding_resolves_connected_workflow(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_mcp_record_by_id_and_tenant", MagicMock(
        return_value={"mcp_id": 5, "mcp_name": "github"}
    ))
    monkeypatch.setattr(
        nl2agent_service,
        "find_mcp_workflow_by_id",
        MagicMock(return_value=("registry:github", {"status": "connected"})),
    )
    update_workflow = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_mcp_workflow", update_workflow)

    result = await nl2agent_service.skip_mcp_tool_binding(202, 5, "tenant_1")

    assert result["status"] == "binding_skipped"
    update_workflow.assert_called_once_with(
        "tenant_1",
        202,
        "registry:github",
        status="binding_skipped",
        bound_tool_ids=[],
    )


@pytest.mark.asyncio
async def test_install_recommended_mcp_resolves_cached_remote_and_redacts_secrets(monkeypatch):
    catalogs = {
        "tool_catalog": [],
        "skill_catalog": [],
        "registry_results": [{
            "server": {
                "name": "github",
                "description": "Repository automation",
                "remotes": [{
                    "url": "https://${workspace}.example/{region}/sse",
                    "type": "sse",
                    "variables": [
                        {"name": "workspace", "isRequired": True},
                        {"name": "region", "isRequired": True},
                    ],
                    "headers": [{
                        "name": "Authorization", "isRequired": True, "isSecret": True,
                    }],
                }],
            }
        }],
        "community_results": [],
        "official_skills": [],
    }
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_nl2agent_session_catalogs", MagicMock(
        return_value=catalogs
    ))
    add_mcp = AsyncMock()
    monkeypatch.setattr(nl2agent_service, "add_mcp_service", add_mcp)
    monkeypatch.setattr(nl2agent_service, "get_mcp_records_by_tenant", MagicMock(
        return_value=[{"mcp_id": 5, "mcp_name": "github", "mcp_server": "https://mcp.example/sse"}]
    ))
    monkeypatch.setattr(nl2agent_service, "get_tool_from_remote_mcp_server", AsyncMock(
        return_value=[MagicMock()]
    ))
    monkeypatch.setattr(nl2agent_service, "upsert_discovered_mcp_tools", MagicMock(
        return_value=[{"tool_id": 11, "name": "create_issue", "description": "Create issue"}]
    ))
    set_catalogs = MagicMock()
    monkeypatch.setattr(nl2agent_service, "set_nl2agent_session_catalogs", set_catalogs)

    result = await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="registry:github",
        option_id="remote-0",
        config_values={"fields": {
            "variable:workspace:0": "acme",
            "variable:region:1": "eu",
            "header:Authorization:0": "secret-token",
        }},
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result == {
        "agent_id": 202,
        "mcp_id": 5,
        "status": "connected",
        "tools": [{"tool_id": 11, "name": "create_issue", "description": "Create issue"}],
    }
    assert "secret-token" not in str(result)
    assert add_mcp.call_args.kwargs["server_url"] == "https://acme.example/eu/sse"
    assert add_mcp.call_args.kwargs["authorization_token"] == "secret-token"
    assert set_catalogs.call_args.args[2]["registry_results"] == []


@pytest.mark.asyncio
async def test_install_recommended_mcp_rejects_missing_declared_remote_variable(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_nl2agent_session_catalogs", MagicMock(
        return_value={
            "tool_catalog": [], "skill_catalog": [], "community_results": [], "official_skills": [],
            "registry_results": [{"server": {
                "name": "required-config",
                "remotes": [{
                    "url": "https://{workspace}.example/mcp",
                    "variables": [{"name": "workspace", "isRequired": True}],
                }],
            }}],
        }
    ))

    with pytest.raises(nl2agent_service.AgentRunException, match="Missing required MCP configuration"):
        await nl2agent_service.install_recommended_mcp(
            agent_id=202,
            recommendation_id="registry:required-config",
            option_id="remote-0",
            config_values={"fields": {}},
            tenant_id="tenant_1",
            user_id="user_1",
        )

    workflow = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["registry:required-config"]
    assert workflow["status"] == "failed"
    assert "config_values" not in workflow


@pytest.mark.asyncio
async def test_install_recommended_package_preserves_registry_arguments_and_environment(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    monkeypatch.setattr(nl2agent_service, "get_nl2agent_session_catalogs", MagicMock(
        return_value={
            "tool_catalog": [], "skill_catalog": [], "community_results": [], "official_skills": [],
            "registry_results": [{"server": {
                "name": "package-mcp",
                "packages": [{
                    "registryType": "npm",
                    "runtimeHint": "npx",
                    "identifier": "@example/package-mcp",
                    "transport": {"type": "stdio"},
                    "runtimeArguments": [{"type": "positional", "value": "--yes"}],
                    "packageArguments": [{"type": "named", "name": "--mode", "value": "safe"}],
                    "environmentVariables": [{"name": "REGION", "value": "eu"}],
                }],
            }}],
        }
    ))
    add_container = AsyncMock()
    monkeypatch.setattr(nl2agent_service, "add_container_mcp_service", add_container)
    monkeypatch.setattr(nl2agent_service, "get_mcp_records_by_tenant", MagicMock(
        return_value=[{"mcp_id": 6, "mcp_name": "package-mcp", "mcp_server": "container"}]
    ))
    monkeypatch.setattr(nl2agent_service, "get_tool_from_remote_mcp_server", AsyncMock(
        return_value=[]
    ))
    monkeypatch.setattr(nl2agent_service, "upsert_discovered_mcp_tools", MagicMock(return_value=[]))
    monkeypatch.setattr(nl2agent_service, "set_nl2agent_session_catalogs", MagicMock())

    await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="registry:package-mcp",
        option_id="package-0",
        config_values={"fields": {"container:port:0": "5010"}},
        tenant_id="tenant_1",
        user_id="user_1",
    )

    server = add_container.call_args.kwargs["mcp_config"].mcpServers["package-mcp"]
    assert server.command == "npx"
    assert server.args == ["--yes", "@example/package-mcp", "--mode=safe"]
    assert server.env == {"REGION": "eu"}


@pytest.mark.asyncio
async def test_install_community_container_merges_card_secret_without_persisting_it(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={"agent_id": 202, "name": "draft_test"}
    ))
    raw = {
        "communityId": 55,
        "name": "community-container",
        "transportType": "container",
        "configJson": {"mcpServers": {"community-container": {
            "command": "npx", "args": ["package"], "env": {"API_TOKEN": None},
        }}},
    }
    monkeypatch.setattr(nl2agent_service, "get_nl2agent_session_catalogs", MagicMock(
        return_value={
            "tool_catalog": [], "skill_catalog": [], "registry_results": [],
            "community_results": [raw], "official_skills": [],
        }
    ))
    add_container = AsyncMock()
    monkeypatch.setattr(nl2agent_service, "add_container_mcp_service", add_container)
    monkeypatch.setattr(nl2agent_service, "get_mcp_records_by_tenant", MagicMock(
        return_value=[{"mcp_id": 7, "mcp_name": "community-container", "mcp_server": "container"}]
    ))
    monkeypatch.setattr(nl2agent_service, "get_tool_from_remote_mcp_server", AsyncMock(
        return_value=[]
    ))
    monkeypatch.setattr(nl2agent_service, "upsert_discovered_mcp_tools", MagicMock(return_value=[]))
    monkeypatch.setattr(nl2agent_service, "set_nl2agent_session_catalogs", MagicMock())

    await nl2agent_service.install_recommended_mcp(
        agent_id=202,
        recommendation_id="community:55",
        option_id="community-container",
        config_values={"fields": {
            "container:port:0": "5020",
            "environment:API_TOKEN:0": "secret-token",
        }},
        tenant_id="tenant_1",
        user_id="user_1",
    )

    config = add_container.call_args.kwargs["mcp_config"]
    assert config.mcpServers["community-container"].env == {"API_TOKEN": "secret-token"}
    workflow = nl2agent_session_catalog.get_nl2agent_session_state("tenant_1", 202)[
        "mcp_workflows"
    ]["community:55"]
    assert "secret-token" not in str(workflow)


@pytest.mark.asyncio
async def test_install_web_skill_installs_by_skill_name(monkeypatch):
    install_from_zip = MagicMock(return_value=["search-web-tavily"])
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 12,
                    "skill_name": "search-web-tavily",
                    "status": "installable",
                },
                {
                    "skill_id": 13,
                    "skill_name": "code-review",
                    "status": "installable",
                },
            ],
        },
    )

    result = await nl2agent_service.install_web_skill(
        agent_id=202,
        skill_id=0,
        skill_name="search-web-tavily",
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )

    install_from_zip.assert_called_once_with(
        skill_names=["search-web-tavily"],
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )
    assert result == {
        "skill_id": 0,
        "skill_name": "search-web-tavily",
        "installed": True,
        "installed_ids": [],
        "installed_names": ["search-web-tavily"],
    }
    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        {
            "skill_id": 13,
            "skill_name": "code-review",
            "status": "installable",
        }
    ]


@pytest.mark.asyncio
async def test_install_web_skill_still_installs_by_legacy_skill_id(monkeypatch):
    install_by_id = MagicMock(return_value=[107])
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )
    monkeypatch.setattr(nl2agent_service, "install_skills_for_tenant", install_by_id)
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [
                {
                    "skill_id": 77,
                    "skill_name": "legacy-source",
                    "status": "installable",
                },
                {
                    "skill_id": 88,
                    "skill_name": "keep-me",
                    "status": "installable",
                },
            ],
        },
    )

    result = await nl2agent_service.install_web_skill(
        agent_id=202,
        skill_id=77,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    install_by_id.assert_called_once_with(
        skill_ids=[77], tenant_id="tenant_1", user_id="user_1"
    )
    assert result == {
        "skill_id": 77,
        "installed": True,
        "installed_ids": [107],
    }
    assert get_nl2agent_session_catalogs("tenant_1", 202)["official_skills"] == [
        {"skill_id": 88, "skill_name": "keep-me", "status": "installable"}
    ]


@pytest.mark.asyncio
async def test_install_web_skill_validates_draft_ownership(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    install_from_zip = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )

    with pytest.raises(nl2agent_service.AgentRunException, match="draft agent not found"):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=0,
            skill_name="search-web-tavily",
            tenant_id="other_tenant",
            user_id="user_1",
        )

    install_from_zip.assert_not_called()


@pytest.mark.asyncio
async def test_install_web_skill_rejects_resource_missing_catalog_item(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )
    install_from_zip = MagicMock()
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )
    nl2agent_session_catalog.set_nl2agent_session_catalogs(
        "tenant_1",
        202,
        {
            **_EXPECTED_SESSION_CATALOGS,
            "official_skills": [{
                "skill_id": 12,
                "skill_name": "missing-files",
                "status": "resource_missing",
            }],
        },
    )

    with pytest.raises(
        nl2agent_service.AgentRunException, match="not available for installation"
    ):
        await nl2agent_service.install_web_skill(
            agent_id=202,
            skill_id=12,
            skill_name="missing-files",
            tenant_id="tenant_1",
            user_id="user_1",
        )

    install_from_zip.assert_not_called()


@pytest.mark.asyncio
async def test_apply_local_resources_batch_binds_tools_and_installed_skills_to_draft(
    monkeypatch,
):
    query_tools = MagicMock(return_value=[{"tool_id": 42, "params": {"path": "/tmp"}}])
    bind_tool = MagicMock()
    get_tenant_skill = MagicMock(return_value=None)
    install_skill = MagicMock(return_value=[107])
    bind_skill = MagicMock()

    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", query_tools)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(nl2agent_service, "get_tenant_skill_by_id", get_tenant_skill)
    monkeypatch.setattr(nl2agent_service, "install_skills_for_tenant", install_skill)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )
    monkeypatch.setattr(nl2agent_service, "_get_owned_draft", MagicMock(return_value={"agent_id": 202}))
    nl2agent_session_catalog.register_recommendation_batch("tenant_1", 202, "batch_1", [42], [7])

    result = await nl2agent_service.apply_local_resources_batch(
        agent_id=202,
        recommendation_batch_id="batch_1",
        tool_ids=[42],
        skill_ids=[7],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result == {
        "recommendation_batch_id": "batch_1",
        "status": "applied",
        "bound_tool_count": 1,
        "bound_skill_count": 1,
        "tool_ids": [42],
        "skill_ids": [107],
        "chat_injection_text": nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT,
    }

    tool_request = bind_tool.call_args.kwargs["tool_info"]
    assert tool_request.tool_id == 42
    assert tool_request.agent_id == 202
    assert tool_request.params == {"path": "/tmp"}
    assert tool_request.enabled is True
    bind_tool.assert_called_once()

    get_tenant_skill.assert_called_once_with(7, "tenant_1")
    install_skill.assert_called_once_with(
        skill_ids=[7], tenant_id="tenant_1", user_id="user_1"
    )
    skill_request = bind_skill.call_args.kwargs["skill_info"]
    assert skill_request.skill_id == 107
    assert skill_request.agent_id == 202
    assert skill_request.enabled is True
    assert skill_request.version_no == 0
    bind_skill.assert_called_once()


@pytest.mark.asyncio
async def test_apply_local_resources_batch_ignores_catalog_param_schema(monkeypatch):
    query_tools = MagicMock(
        return_value=[
            {
                "tool_id": 42,
                "params": [
                    {
                        "type": "integer",
                        "name": "top_k",
                        "default": None,
                        "optional": True,
                    }
                ],
            }
        ]
    )
    bind_tool = MagicMock()

    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", query_tools)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(nl2agent_service, "_get_owned_draft", MagicMock(return_value={"agent_id": 202}))
    nl2agent_session_catalog.register_recommendation_batch("tenant_1", 202, "batch_1", [42], [])

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
    assert tool_request.params == {}


@pytest.mark.asyncio
async def test_apply_local_resources_batch_rejects_invalid_draft_agent_id(monkeypatch):
    query_tools = MagicMock()
    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", query_tools)

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
            tool_ids=[],
            skill_ids=[],
            sub_agent_ids=[],
        )

    update_agent.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_uses_persisted_resources_and_ignores_generated_ids(monkeypatch):
    draft = {
        "agent_id": 202,
        "name": "draft_test",
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
        MagicMock(return_value=[{
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "available",
            "display_name": "Primary LLM",
        }]),
    )
    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", MagicMock(return_value=None)
    )
    update = MagicMock()
    bind_tool = MagicMock()
    bind_skill = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    monkeypatch.setattr(nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool)
    monkeypatch.setattr(nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill)
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
        "query_tools_by_ids",
        MagicMock(return_value=[{
            "tool_id": 42,
            "origin_name": "Document Parser",
            "source": "local",
        }]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(return_value=[{
            "skill_id": 7,
            "name": "Presentation Builder",
            "source": "custom",
        }]),
    )
    nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [42], [7]
    )
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "applied", [42], [7]
    )
    _complete_required_online_review()
    nl2agent_session_catalog.confirm_agent_identity("tenant_1", 202)

    result = await nl2agent_service.finalize_agent(
        agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        name="llm_invented_name",
        display_name="Document Helper",
        business_description="Build document presentations",
        duty_prompt="Create presentations from documents.",
        greeting_message="Upload a document to begin.",
        tool_ids=[999],
        skill_ids=[888],
        tool_configs={"999": {"fabricated": True}},
        skill_configs={"888": {"fabricated": True}},
    )

    assert result["name"] == "old_title"
    assert result["display_name"] == "Old title"
    assert result["tool_ids"] == [42]
    assert result["skill_ids"] == [7]
    bind_tool.assert_not_called()
    bind_skill.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_rejects_dangling_resources_before_updating_draft(monkeypatch):
    draft = {
        "agent_id": 202,
        "name": "draft_test",
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
        MagicMock(return_value=[{
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "available",
            "display_name": "Primary LLM",
        }]),
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
    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", MagicMock(return_value=[]))
    update = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [404], []
    )
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "applied", [404], []
    )
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
        MagicMock(return_value=[{
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "available",
            "display_name": "Primary LLM",
        }]),
    )
    nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [], []
    )
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
async def test_finalize_rejects_connected_mcp_until_tools_are_bound_or_skipped(monkeypatch):
    _confirm_requirements()
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", MagicMock(
        return_value={
            "agent_id": 202,
            "name": "draft_test",
            "display_name": "Document Helper",
            "business_logic_model_id": 7,
            "model_ids": [7],
        }
    ))
    monkeypatch.setattr(nl2agent_service, "get_model_records", MagicMock(return_value=[
        {
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "available",
            "display_name": "Primary LLM",
        },
    ]))
    nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [], []
    )
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

    with pytest.raises(nl2agent_service.AgentRunException, match="Bind discovered MCP tools"):
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
    nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, "batch_1", [], []
    )
    nl2agent_session_catalog.resolve_recommendation_batch(
        "tenant_1", 202, "batch_1", "skipped"
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
        nl2agent_service.AgentRunException,
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
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    assert nl2agent_service._generate_internal_agent_name(
        display_name, 202, "tenant_1"
    ) == expected


def test_generate_internal_agent_name_appends_agent_id_for_duplicate(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", MagicMock(return_value=99)
    )
    assert nl2agent_service._generate_internal_agent_name(
        "Customer Support", 202, "tenant_1"
    ) == "customer_support_202"


def test_generate_internal_agent_name_preserves_unexpected_database_error(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        nl2agent_service._generate_internal_agent_name(
            "Customer Support", 202, "tenant_1"
        )


def test_generate_internal_agent_name_preserves_unexpected_value_error(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
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
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )
    update = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update)
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
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
    assert nl2agent_session_catalog.get_nl2agent_session_state(
        "tenant_1", 202
    )["identity_confirmed"]


@pytest.mark.asyncio
async def test_save_agent_identity_rejects_whitespace(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )
    with pytest.raises(nl2agent_service.AgentRunException, match="cannot be empty"):
        await nl2agent_service.save_agent_identity(
            202, "   ", "tenant_1", "user_1"
        )


@pytest.mark.asyncio
async def test_online_recommendation_registration_and_completion(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )

    registered = await nl2agent_service.register_online_resource_recommendations(
        202, "online_1", "skill", ["skill:7"], "tenant_1"
    )
    assert registered["status"] == "recommendations_ready"
    mcp_registered = await nl2agent_service.register_online_resource_recommendations(
        202, "online_mcp", "mcp", [], "tenant_1"
    )
    assert mcp_registered["status"] == "recommendations_ready"

    completed = await nl2agent_service.confirm_online_resource_configuration(
        202, "tenant_1"
    )
    assert completed == {
        "agent_id": 202,
        "online_configuration_confirmed": True,
        "completed_batch_ids": ["online_1", "online_mcp"],
        "chat_injection_text": nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT,
    }


@pytest.mark.asyncio
async def test_local_skip_returns_automatic_continuation_text(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={"agent_id": 202, "name": "draft_test"}),
    )
    nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, "local_empty", [], []
    )

    result = await nl2agent_service.skip_local_resource_recommendations(
        202, "local_empty", "tenant_1"
    )

    assert result["status"] == "skipped"
    assert (
        result["chat_injection_text"]
        == nl2agent_service.NL2AGENT_CHAT_INJECTION_TEXT
    )


@pytest.mark.asyncio
async def test_get_session_state_returns_generated_name_when_candidate_is_available(
    monkeypatch,
):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(
            return_value={
                "agent_id": 202,
                "display_name": "Customer Support",
                "business_logic_model_id": 7,
                "model_ids": [7],
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
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
        MagicMock(return_value=[{
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "available",
            "display_name": "Primary LLM",
        }]),
    )

    result = await nl2agent_service.get_session_state(202, "tenant_1")

    assert result["agent_id"] == 202
    assert result["internal_name"] == "customer_support"
    assert result["business_logic_model_id"] == 7
    assert result["model_ids"] == [7]
    assert result["models"] == [{
        "model_id": 7,
        "display_name": "Primary LLM",
        "role": "primary",
        "valid": True,
    }]
    assert result["invalid_references"] == []


@pytest.mark.asyncio
async def test_get_session_state_resolves_names_and_resource_origins(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={
            "agent_id": 202,
            "display_name": "Document Assistant",
            "business_logic_model_id": 7,
            "model_ids": [7, 8],
        }),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(return_value=[
            {
                "model_id": 7,
                "model_type": "llm",
                "connect_status": "available",
                "display_name": "Primary LLM",
            },
            {
                "model_id": 8,
                "model_type": "llm",
                "connect_status": "available",
                "model_name": "Fallback LLM",
            },
        ]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(return_value=[{"tool_id": 11}, {"tool_id": 12}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_tools_by_ids",
        MagicMock(return_value=[
            {"tool_id": 11, "origin_name": "Local Reader", "source": "local"},
            {"tool_id": 12, "name": "Web Fetch", "source": "mcp"},
        ]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[{"skill_id": 21}, {"skill_id": 22}]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "query_skills_by_ids",
        MagicMock(return_value=[
            {"skill_id": 21, "name": "Local Skill", "source": "custom"},
            {"skill_id": 22, "name": "Official Skill", "source": "official"},
        ]),
    )

    result = await nl2agent_service.get_session_state(202, "tenant_1")

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
    assert result["invalid_references"] == []


@pytest.mark.asyncio
async def test_get_session_state_reports_invalid_persisted_references(monkeypatch):
    monkeypatch.setattr(
        nl2agent_service,
        "_get_owned_draft",
        MagicMock(return_value={
            "agent_id": 202,
            "display_name": "Document Assistant",
            "business_logic_model_id": 7,
            "model_ids": [7],
        }),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "search_agent_id_by_agent_name",
        MagicMock(side_effect=ValueError("agent not found")),
    )
    monkeypatch.setattr(nl2agent_service, "get_model_records", MagicMock(return_value=[]))
    monkeypatch.setattr(
        nl2agent_service,
        "query_all_enabled_tool_instances",
        MagicMock(return_value=[{"tool_id": 11}]),
    )
    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", MagicMock(return_value=[]))
    monkeypatch.setattr(
        nl2agent_service,
        "query_enabled_skill_instances",
        MagicMock(return_value=[{"skill_id": 21}]),
    )
    monkeypatch.setattr(nl2agent_service, "query_skills_by_ids", MagicMock(return_value=[]))

    result = await nl2agent_service.get_session_state(202, "tenant_1")

    assert result["tools"] == []
    assert result["skills"] == []
    assert result["invalid_references"] == [
        {"reference_type": "model", "reference_id": 7, "reason": "not_found"},
        {"reference_type": "tool", "reference_id": 11, "reason": "not_found"},
        {"reference_type": "skill", "reference_id": 21, "reason": "not_found"},
    ]


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
