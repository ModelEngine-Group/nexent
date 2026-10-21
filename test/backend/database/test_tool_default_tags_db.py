# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from database.db_models import ResourceTagAssignment, TagDefinition, TagValue
from database.tool_default_tags_db import initialize_search_tool_tags


@pytest.fixture
def tags(mocker):
    session = MagicMock()
    binding = mocker.patch(
        "database.tool_default_tags_db.TagManagementDB._get_active_resource_binding",
        return_value=SimpleNamespace(bucket_id=3),
    )
    definition = TagDefinition(definition_id=4, status="active", selection_mode="multi_select")
    value = TagValue(value_id=5, status="active")
    queries = [MagicMock() for _ in range(3)]
    for query, row in zip(queries, (definition, value, None)):
        query.filter.return_value = query
        query.one_or_none.return_value = row
    session.query.side_effect = queries
    return session, binding, queries, definition, value


def test_search_assignment_uses_canonical_tenant_scoped_keyword(tags):
    session, binding, queries, _, _ = tags
    initialize_search_tool_tags(session, "tenant", 220, "actor")
    binding.assert_called_once_with(session, "tenant", "tool", "default_resource", for_update=True)
    assignment = session.add.call_args.args[0]
    assert isinstance(assignment, ResourceTagAssignment)
    assert (assignment.tenant_id, assignment.resource_type, assignment.resource_id) == ("tenant", "tool", "220")
    assert (assignment.definition_id, assignment.value_id) == (4, 5)
    assert (assignment.created_by, assignment.updated_by, assignment.delete_flag) == ("actor", "actor", "N")
    for query in queries:
        predicates = query.filter.call_args.args
        assert any(str(predicate.left).endswith("tenant_id") and predicate.right.value == "tenant"
                   for predicate in predicates)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_missing_keywords_definition_and_search_value_are_created(tags):
    session, _, queries, _, _ = tags
    queries[0].one_or_none.return_value = None
    queries[1].one_or_none.return_value = None

    def allocate_ids():
        for call in session.add.call_args_list:
            row = call.args[0]
            if isinstance(row, TagDefinition):
                row.definition_id = 4
            elif isinstance(row, TagValue):
                row.value_id = 5

    session.flush.side_effect = allocate_ids
    initialize_search_tool_tags(session, "tenant", 220, "actor")
    definition, value, assignment = [call.args[0] for call in session.add.call_args_list]
    assert definition.definition_key == "keywords"
    assert definition.definition_name == "Keywords"
    assert "normalized_name" not in definition.__dict__
    assert definition.bucket_id == 3
    assert value.display_value == value.normalized_value == "search"
    assert assignment.definition_id == value.definition_id == 4
    assert assignment.value_id == 5


@pytest.mark.parametrize("kind", ["definition", "value", "existing_assignment"])
def test_disabled_or_existing_tags_are_never_overwritten(tags, kind):
    session, _, queries, definition, value = tags
    if kind == "definition":
        definition.status = "disabled"
    elif kind == "value":
        value.status = "disabled"
    else:
        queries[2].one_or_none.return_value = SimpleNamespace(delete_flag="Y", status="disabled")
    initialize_search_tool_tags(session, "tenant", 220, "actor")
    session.add.assert_not_called()


def test_tag_failure_propagates_to_tool_registration_transaction(tags):
    session, binding, _, _, _ = tags
    binding.side_effect = ValueError("binding unavailable")
    with pytest.raises(ValueError, match="binding unavailable"):
        initialize_search_tool_tags(session, "tenant", 220, "actor")
    session.add.assert_not_called()
