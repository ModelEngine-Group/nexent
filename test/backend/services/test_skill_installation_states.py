# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing published sources count as installed without becoming uninstallable copies."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from management.services.repository import skill_installations as installations


@pytest.mark.parametrize(
    "visible, expected_state, expected_copies",
    [
        ([{"skill_id": 10, "name": "original", "source": "custom"}], "installed", []),
        ([{"skill_id": 10, "name": "renamed", "source": "official"}], "installed", []),
        ([{"skill_id": 11, "name": "original", "source": "custom"}], "not_installed", []),
        ([{"skill_id": 20, "name": "copy", "source": "repository", "source_repository_id": 1,
           "permission": "EDIT"}], "installed", [{"skill_id": 20, "name": "copy", "can_uninstall": True}]),
        ([{"skill_id": 20, "name": "copy", "source": "repository", "source_repository_id": 1,
           "permission": "READ_ONLY"}], "installed", [{"skill_id": 20, "name": "copy", "can_uninstall": False}]),
        ([], "not_installed", []),
        ([{"skill_id": 20, "name": "legacy", "source": "repository"}], "unknown", []),
    ],
)
def test_existing_sources_and_linked_copies_use_ids(visible, expected_state, expected_copies):
    result = installations.installation_states([1], visible, {1: 10})
    assert result["1"] == {"installation_state": expected_state, "installed_copies": expected_copies}


def test_owned_source_is_known_even_when_other_historical_copies_are_unlinked():
    result = installations.installation_states(
        [1, 2],
        [{"skill_id": 10, "name": "original"}, {"skill_id": 20, "name": "legacy", "source": "repository"}],
        {1: 10},
    )
    assert result["1"]["installation_state"] == "installed"
    assert result["2"]["installation_state"] == "unknown"


def test_batch_lookup_filters_visibility_and_keeps_tenant_and_deletion_scope():
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = [
        {"skill_id": 10, "skill_name": "visible", "source": "custom", "source_repository_id": None,
         "created_by": "other", "group_ids": "7", "ingroup_permission": "READ_ONLY"},
        {"skill_id": 11, "skill_name": "hidden", "source": "custom", "source_repository_id": None,
         "created_by": "other", "group_ids": "8", "ingroup_permission": "READ_ONLY"},
    ]
    context = MagicMock()
    context.__enter__.return_value = session
    with patch.object(installations, "get_db_session", return_value=context), \
            patch.object(installations, "query_group_ids_by_user", return_value=[7]):
        result = installations.get_installation_states(
            [1, 2], "tenant", "viewer", ("USER",), source_skill_ids={1: 10, 2: 11}
        )
    assert result["1"] == {"installation_state": "installed", "installed_copies": []}
    assert result["2"]["installation_state"] == "not_installed"
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "tenant_id =" in sql and "delete_flag !=" in sql
    assert "source_repository_id IN" in sql and "skill_id IN" in sql
    assert "tenant" in statement.params.values()


def test_empty_page_does_not_query_group_or_skill_data():
    with patch.object(installations, "get_db_session") as session, \
            patch.object(installations, "query_group_ids_by_user") as groups:
        assert installations.get_installation_states([], "tenant", "viewer", ("USER",)) == {}
    session.assert_not_called()
    groups.assert_not_called()
