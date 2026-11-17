# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Conversation directory groups and keyset pages stay authorization bound."""

from unittest.mock import Mock

import pytest
from ops.services.trajectory.access import Actor
from ops.services.trajectory.directory import directory
from ops.services.trajectory.primitives import Budget, QueryError, ReferenceStore

ACTOR = Actor("admin", "t", "OPS")


@pytest.fixture
def service():
    instance = Mock(execution_catalog=None)
    instance.references = ReferenceStore()
    instance.budget.side_effect = Budget
    instance.catalog.actor_active.return_value = True
    instance.catalog.tenants.return_value = ["t"]
    instance.catalog.user_active.return_value = True
    instance.catalog.agent_names.return_value = {("t", "7"): "Agent"}
    instance.catalog.directory_page.return_value = [
        {
            "tenant_id": "t",
            "user_id": "u",
            "conversation_id": str(index),
            "conversation_title": "Question",
            "agent_id": agent,
        }
        for index, agent in ((1, None), (2, "7"), (3, "8"))
    ]
    return instance


@pytest.mark.parametrize(
    "params,code",
    [
        ({"target_user_id": ""}, "invalid_directory_parameters"),
        ({"category": "bad"}, "invalid_directory_parameters"),
        ({"limit": 0}, "invalid_directory_parameters"),
        ({"group_key": "bad"}, "invalid_group"),
    ],
)
def test_directory_parameters_are_checked_before_candidates(service, params, code):
    with pytest.raises(QueryError, match=code):
        directory(service, ACTOR, **{"target_user_id": "u", **params})
    service.catalog.directory_page.assert_not_called()


def test_inactive_owner_has_no_directory(service):
    service.catalog.user_active.return_value = False
    with pytest.raises(QueryError, match="trajectory_not_found"):
        directory(service, ACTOR, target_user_id="u")
    service.archive.manifest.assert_not_called()


def test_group_directory_preserves_other_and_agent_names_and_uses_cursor(service):
    first = directory(service, ACTOR, target_user_id="u", limit=2)
    assert first["items"] == [
        {"group_key": "other", "agent_id": None, "agent_name": "Other"},
        {"group_key": "agent:7", "agent_id": "7", "agent_name": "Agent"},
    ]
    second = directory(
        service, ACTOR, target_user_id="u", limit=2, cursor=first["next_cursor"]
    )
    assert second["items"] == []
    assert service.catalog.directory_page.call_args.args[-3:] == (7, 2, "")
    assert first["included"] == first["pinned"] == []


def test_group_page_only_returns_corresponding_conversations(service):
    response = directory(service, ACTOR, target_user_id="u", group_key="agent:7")
    assert response["items"] == [
        {"conversation_id": "2", "conversation_title": "Question", "agent_id": "7"}
    ]
    response = directory(service, ACTOR, target_user_id="u", group_key="other")
    assert response["items"][0]["agent_id"] is None


@pytest.mark.parametrize("status", [404, 503])
def test_legacy_directory_skips_missing_archive_but_propagates_storage_errors(
    service, status
):
    service.archive.manifest.side_effect = QueryError("unavailable", status)
    if status == 404:
        assert directory(service, ACTOR, target_user_id="u")["items"] == []
        service.recheck.assert_not_called()
    else:
        with pytest.raises(QueryError, match="unavailable"):
            directory(service, ACTOR, target_user_id="u")
