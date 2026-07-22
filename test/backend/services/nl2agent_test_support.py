"""Shared fixtures and builders for focused NL2AGENT service tests."""
# ruff: noqa: F401

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest
from pydantic import ValidationError

from agents import nl2agent_session_catalog
from agents import nl2agent_session_store
from agents.nl2agent_session_catalog import (
    get_nl2agent_session_catalogs,
)
from consts.exceptions import (
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentStaleCardError,
    Nl2AgentValidationError,
    Nl2AgentWorkflowConflictError,
)
from consts.model import Nl2AgentFinalizeRequest
from consts.nl2agent_response import (
    Nl2AgentApplyLocalResourcesResponse,
    Nl2AgentFinalizeResponse,
    Nl2AgentLocalRecommendationResponse,
    Nl2AgentModelSelectionResponse,
    Nl2AgentOnlineRecommendationResponse,
    Nl2AgentSessionStartResponse,
    Nl2AgentSessionStateResponse,
    Nl2AgentWebSkillInstallResponse,
)
from nexent.core.tools.nl2agent.search_local_resources_tool import (
    get_search_local_resources_tool,
)
from services import nl2agent_catalog_service, nl2agent_mcp_service, nl2agent_service
from services.nl2agent_resource_service import (
    _resolve_tool_config_values,
    redact_tool_parameter_defaults,
)
from services.nl2agent_seed_service import NL2AGENT_VERIFICATION_CONFIG


@pytest.fixture(autouse=True)
def _active_nl2agent_session(monkeypatch):
    """Keep workflow unit tests focused beyond the session authorization boundary."""
    monkeypatch.setattr(
        nl2agent_service,
        "require_active_session",
        MagicMock(
            return_value={
                "runner_agent_id": 101,
                "draft_agent_id": 202,
                "conversation_id": 902,
                "status": "active",
            }
        ),
    )


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
        "inputs": {
            "query": {"type": "string", "description": "Runtime query"}
        },
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


def clear_nl2agent_session_catalogs():
    """Reset only the per-test fake Redis database."""
    nl2agent_session_store.get_redis_service().client.flushdb()


def _confirm_requirements(tenant_id="tenant_1", draft_agent_id=202):
    review = nl2agent_session_catalog.register_requirements_summary(
        tenant_id, draft_agent_id, _REQUIREMENTS_SUMMARY
    )
    nl2agent_session_catalog.confirm_requirements_summary(
        tenant_id, draft_agent_id, review["fingerprint"]
    )


def _prepare_required_online_review(tenant_id="tenant_1", draft_agent_id=202):
    _confirm_requirements(tenant_id, draft_agent_id)
    nl2agent_session_catalog.set_model_selection_confirmed(
        tenant_id, draft_agent_id, True
    )
    nl2agent_session_catalog._record_trusted_search_batch(
        tenant_id,
        draft_agent_id,
        recommendation_batch_id="local_empty",
        resource_type="local",
        tool_ids=[],
        skill_ids=[],
    )
    nl2agent_session_catalog.register_recommendation_batch(
        tenant_id, draft_agent_id, "local_empty", [], []
    )
    nl2agent_session_catalog.resolve_recommendation_batch(
        tenant_id, draft_agent_id, "local_empty", "skipped"
    )
    nl2agent_session_catalog._record_trusted_search_batch(
        tenant_id,
        draft_agent_id,
        recommendation_batch_id="online_mcp",
        resource_type="mcp",
        item_keys=[],
    )
    nl2agent_session_catalog.register_online_recommendation_batch(
        tenant_id, draft_agent_id, "online_mcp", "mcp", []
    )
    nl2agent_session_catalog._record_trusted_search_batch(
        tenant_id,
        draft_agent_id,
        recommendation_batch_id="online_skill",
        resource_type="skill",
        item_keys=[],
    )
    nl2agent_session_catalog.register_online_recommendation_batch(
        tenant_id, draft_agent_id, "online_skill", "skill", []
    )


def _complete_required_online_review(tenant_id="tenant_1", draft_agent_id=202):
    _prepare_required_online_review(tenant_id, draft_agent_id)
    nl2agent_session_catalog.complete_online_configuration(tenant_id, draft_agent_id)


def _register_local_batch(batch_id, tool_ids, skill_ids):
    nl2agent_session_catalog._record_trusted_search_batch(
        "tenant_1",
        202,
        recommendation_batch_id=batch_id,
        resource_type="local",
        tool_ids=tool_ids,
        skill_ids=skill_ids,
    )
    return nl2agent_session_catalog.register_recommendation_batch(
        "tenant_1", 202, batch_id, tool_ids, skill_ids
    )


def _complete_local_apply(batch_id, tool_ids, skill_ids):
    operation_id = f"test-apply:{batch_id}"
    nl2agent_session_catalog.reserve_recommendation_batch_apply(
        "tenant_1", 202, batch_id, operation_id, tool_ids, skill_ids
    )
    return nl2agent_session_catalog.complete_recommendation_batch_apply(
        "tenant_1", 202, batch_id, operation_id
    )


def _mock_database_transaction(monkeypatch):
    session = MagicMock(name="shared_db_session")
    transaction = MagicMock(name="database_transaction")
    transaction.__enter__.return_value = session
    transaction.__exit__.return_value = False
    monkeypatch.setattr(
        nl2agent_service, "get_db_session", MagicMock(return_value=transaction)
    )
    return session, transaction


def _mock_selectable_models(monkeypatch):
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
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Primary",
                },
                {
                    "model_id": 8,
                    "model_type": "llm",
                    "connect_status": "available",
                    "display_name": "Fallback",
                },
            ]
        ),
    )


@pytest.fixture(autouse=True)
def mock_nl2agent_seed_defaults(monkeypatch):
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        nl2agent_session_catalog,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=fake_redis)),
    )
    monkeypatch.setattr(
        nl2agent_session_store,
        "get_redis_service",
        MagicMock(return_value=MagicMock(client=fake_redis)),
    )
    initial_state = nl2agent_session_catalog.initialize_nl2agent_session_state(
        "tenant_1", 202, conversation_id=902
    )
    durable_snapshot = {
        "tenant_id": "tenant_1",
        "user_id": "user_1",
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": "active",
        "workflow_revision": 0,
        "catalog_snapshot_id": "test-catalog",
        "workflow_state": initial_state,
        "catalog_snapshot": {
            "tool_catalog": [],
            "skill_catalog": [],
            "registry_results": [],
            "community_results": [],
            "official_skills": [],
        },
    }
    cache_catalogs = nl2agent_session_catalog.set_nl2agent_session_catalogs

    def set_session_catalogs(tenant_id, draft_agent_id, catalogs):
        if tenant_id == "tenant_1" and draft_agent_id == 202:
            durable_snapshot["catalog_snapshot"] = deepcopy(catalogs)
        return cache_catalogs(tenant_id, draft_agent_id, catalogs)

    monkeypatch.setattr(
        nl2agent_session_catalog,
        "set_nl2agent_session_catalogs",
        set_session_catalogs,
    )

    def load_durable_session(tenant_id, draft_agent_id):
        if tenant_id != "tenant_1" or draft_agent_id != 202:
            return None
        return deepcopy(durable_snapshot)

    def persist_workflow_state(
        tenant_id,
        draft_agent_id,
        expected_revision,
        workflow_state,
    ):
        if tenant_id != "tenant_1" or draft_agent_id != 202:
            return False
        if durable_snapshot["workflow_revision"] != expected_revision:
            return False
        durable_snapshot["workflow_revision"] = workflow_state["revision"]
        durable_snapshot["workflow_state"] = deepcopy(workflow_state)
        return True

    monkeypatch.setattr(
        nl2agent_session_store,
        "load_durable_session",
        MagicMock(side_effect=load_durable_session),
    )
    monkeypatch.setattr(
        nl2agent_session_store,
        "persist_workflow_state",
        MagicMock(side_effect=persist_workflow_state),
    )
    transaction = MagicMock()
    transaction.__enter__.return_value = MagicMock()
    transaction.__exit__.return_value = None
    monkeypatch.setattr(
        nl2agent_service,
        "get_db_session",
        MagicMock(return_value=transaction),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "update_nl2agent_session_status",
        MagicMock(return_value=True),
    )
    clear_nl2agent_session_catalogs()
    monkeypatch.setattr(
        nl2agent_service,
        "_require_workflow_action",
        MagicMock(),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "build_pinned_httpx_client_factory",
        MagicMock(return_value=MagicMock(name="pinned_httpx_client_factory")),
    )
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
        "seed_nl2agent_builtin_tools",
        MagicMock(return_value=[11, 12, 13]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "create_or_update_tool_by_tool_info",
        MagicMock(),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "validate_nl2agent_remote_mcp_url",
        MagicMock(side_effect=lambda url: url),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_all_tools",
        AsyncMock(return_value=_RAW_TOOL_ROWS),
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
        AsyncMock(return_value={"items": _COMMUNITY_RESULTS}),
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
        "verification_config": NL2AGENT_VERIFICATION_CONFIG,
        "model_ids": [],
    }


__all__ = [
    name
    for name in globals()
    if not name.startswith("__") and not name.startswith("test_")
]
