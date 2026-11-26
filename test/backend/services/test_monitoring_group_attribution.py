# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Initiator group attribution attached to AgentOS run payloads and metadata."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest
from contracts.agentos import RunInput, RunModelBinding
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import context, creator_run
from management.services.skill import creation

GROUP_QUERY = "management.db.identity.group.query_group_ids_by_user_in_tenant"
ACTOR = ServicePrincipal("user", "tenant")
MODEL_SCOPE = {
    "model": RunModelBinding(model_id=11, alias="llm", revision="revision-1"),
    "input_budget": 512,
    "context_window_tokens": 1024,
}


def test_resolver_returns_the_users_tenant_groups(mocker):
    mocker.patch.object(context, "OPS_MONITORING_ENABLED", True)
    query = mocker.patch(GROUP_QUERY, return_value=[3, 1])
    assert context.resolve_initiator_group_ids("user", "tenant") == (3, 1)
    query.assert_called_once_with("user", "tenant")


def test_resolver_keeps_groupless_users_known_empty(mocker):
    mocker.patch.object(context, "OPS_MONITORING_ENABLED", True)
    mocker.patch(GROUP_QUERY, return_value=[])
    assert context.resolve_initiator_group_ids("user", "tenant") == ()


def test_resolver_skips_the_database_when_monitoring_is_disabled(mocker):
    mocker.patch.object(context, "OPS_MONITORING_ENABLED", False)
    query = mocker.patch(GROUP_QUERY)
    assert context.resolve_initiator_group_ids("user", "tenant") is None
    query.assert_not_called()


def test_resolver_reports_lookup_failure_as_unknown(mocker):
    mocker.patch.object(context, "OPS_MONITORING_ENABLED", True)
    mocker.patch(GROUP_QUERY, side_effect=RuntimeError("store down"))
    assert context.resolve_initiator_group_ids("user", "tenant") is None


def test_nl2skill_snapshot_carries_initiator_groups(mocker):
    mocker.patch.object(context, "OPS_MONITORING_ENABLED", True)
    mocker.patch(GROUP_QUERY, return_value=[5])
    mocker.patch.object(creation, "prepare_creator_model", return_value=dict(MODEL_SCOPE))
    mocker.patch.object(creation, "build_evaluation_input", return_value=RunInput(query="build"))

    payload = creation.prepare_nl2skill_snapshot(NL2SkillRunRequest(query="build"), "user", "tenant", "en")

    assert payload.initiator_group_ids == [5]


def test_nl2skill_snapshot_without_groups_leaves_the_field_unknown(mocker):
    mocker.patch.object(context, "OPS_MONITORING_ENABLED", True)
    mocker.patch(GROUP_QUERY, side_effect=RuntimeError("store down"))
    mocker.patch.object(creation, "prepare_creator_model", return_value=dict(MODEL_SCOPE))
    mocker.patch.object(creation, "build_evaluation_input", return_value=RunInput(query="build"))

    payload = creation.prepare_nl2skill_snapshot(NL2SkillRunRequest(query="build"), "user", "tenant", "en")

    assert payload.initiator_group_ids is None


async def test_nl2agent_snapshot_carries_initiator_groups(mocker):
    async def inline(_task, callback, *args, **_kwargs):
        return callback(*args)

    mocker.patch.object(context, "OPS_MONITORING_ENABLED", True)
    mocker.patch(GROUP_QUERY, return_value=[5])
    mocker.patch.object(creator_run, "run_blocking", side_effect=inline)
    mocker.patch.object(creator_run, "prepare_creator_model", return_value=dict(MODEL_SCOPE))
    mocker.patch.object(
        creator_run, "_build_verified_bound_resources_context",
        AsyncMock(return_value=SimpleNamespace(content={"text": "Verified"})),
    )
    mocker.patch.object(creator_run, "build_evaluation_input", return_value=RunInput(query="build"))

    payload = await creator_run.prepare_nl2agent_snapshot(
        NL2AgentRunRequest(query="build", agent_id=201), ACTOR, "en",
    )

    assert payload.initiator_group_ids == [5]
