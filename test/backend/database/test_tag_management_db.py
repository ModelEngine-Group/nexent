from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from consts.exceptions import TagManagementConflictError, TagManagementNotFoundError
from database.db_models import ResourceTagAssignment, TagDefinition
from database.tag_management_db import NO_VALUE_TAG_NORMALIZED_VALUE, TagManagementDB


def record(**values):
    defaults = {
        "created_by": "creator",
        "updated_by": "creator",
        "create_time": None,
        "update_time": None,
        "delete_flag": "N",
        "status": "active",
    }
    return SimpleNamespace(**(defaults | values))


def query(*, one=None, all_=None, count=0):
    item = MagicMock(name="query")
    item.one_or_none.return_value = one
    item.all.return_value = [] if all_ is None else all_
    item.count.return_value = count
    item.filter.return_value = item
    item.join.return_value = item
    item.order_by.return_value = item
    item.group_by.return_value = item
    item.having.return_value = item
    item.with_for_update.return_value = item
    item.distinct.return_value = item
    return item


def db_context(*queries):
    session = MagicMock(name="session")
    session.query.side_effect = list(queries)
    context = MagicMock(name="db_context")
    context.__enter__.return_value = session
    context.__exit__.return_value = None
    return session, context


def install_context(monkeypatch, context):
    monkeypatch.setattr("database.tag_management_db.get_db_session", lambda: context)


def filter_keys(query_mock):
    return {
        (
            criterion.left.key,
            tuple(getattr(criterion.right, "value", ()))
            if isinstance(getattr(criterion.right, "value", None), list)
            else getattr(criterion.right, "value", None),
        )
        for call in query_mock.filter.call_args_list
        for criterion in call.args
        if hasattr(criterion, "left") and hasattr(criterion.left, "key")
    }


def test_lookup_helpers_are_tenant_scoped_and_hide_cross_tenant_records(monkeypatch):
    bucket_query = query(one=None)
    session, context = db_context(bucket_query)
    install_context(monkeypatch, context)

    with pytest.raises(TagManagementNotFoundError, match="Tag library not found"):
        TagManagementDB.list_definitions("tenant-b", 7)
    assert ("tenant_id", "tenant-b") in filter_keys(bucket_query)
    assert ("bucket_id", 7) in filter_keys(bucket_query)

    bucket_query = query(one=record(bucket_id=7, tenant_id="tenant-b", bucket_key="default_resource"))
    definition_query = query(one=None)
    session, context = db_context(bucket_query, definition_query)
    install_context(monkeypatch, context)
    with pytest.raises(TagManagementNotFoundError, match="Tag definition not found"):
        TagManagementDB._get_definition(session, "tenant-b", 7, 9)
    assert ("tenant_id", "tenant-b") in filter_keys(definition_query)
    assert ("definition_id", 9) in filter_keys(definition_query)

    bucket_query = query(one=record(bucket_id=7, tenant_id="tenant-b", bucket_key="default_resource"))
    definition_query = query(one=record(definition_id=9, bucket_id=7, tenant_id="tenant-b"))
    value_query = query(one=None)
    session, context = db_context(bucket_query, definition_query, value_query)
    install_context(monkeypatch, context)
    with pytest.raises(TagManagementNotFoundError, match="Tag value not found"):
        TagManagementDB._get_value(session, "tenant-b", 7, 9, 11)
    assert ("tenant_id", "tenant-b") in filter_keys(value_query)
    assert ("definition_id", 9) in filter_keys(value_query)
    assert ("value_id", 11) in filter_keys(value_query)


def test_list_libraries_and_definitions_include_status_order_audit_and_values(monkeypatch):
    bucket = record(
        bucket_id=1,
        tenant_id="tenant-a",
        bucket_key="default_resource",
        bucket_name="Resources",
        status="disabled",
    )
    binding = record(bucket_id=1, resource_type="agent")
    bucket_query = query(all_=[bucket])
    binding_query = query(all_=[binding])
    counts_query = query(all_=[(1, 2)])
    _session, context = db_context(bucket_query, binding_query, counts_query)
    install_context(monkeypatch, context)
    libraries = TagManagementDB.list_libraries("tenant-a")
    assert libraries[0]["status"] == "disabled"
    assert libraries[0]["resource_types"] == ["agent"]
    assert libraries[0]["definition_count"] == 2
    assert libraries[0]["definition_capacity"] == 100
    assert libraries[0]["updated_by"] == "creator"

    bucket_query = query(one=bucket)
    definition = record(
        definition_id=9,
        bucket_id=1,
        tenant_id="tenant-a",
        definition_key="color",
        definition_name="Color",
        selection_mode="single_select",
        sort_order=3,
    )
    value = record(
        value_id=11,
        definition_id=9,
        tenant_id="tenant-a",
        display_value="Red",
        normalized_value="red",
        sort_order=0,
    )
    definition_query = query(all_=[definition])
    value_query = query(all_=[value])
    _session, context = db_context(bucket_query, definition_query, value_query)
    install_context(monkeypatch, context)
    definitions = TagManagementDB.list_definitions("tenant-a", 1)
    assert definitions[0]["definition_id"] == 9
    assert definitions[0]["values"][0]["value_id"] == 11
    assert definitions[0]["active_value_count"] == 1
    assert definitions[0]["value_capacity"] == 1000


def test_list_definitions_handles_empty_definition_bucket(monkeypatch):
    bucket_query = query(one=record(bucket_id=1, bucket_key="knowledge_content"))
    definition_query = query(all_=[])
    _session, context = db_context(bucket_query, definition_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.list_definitions("tenant-a", 1) == []


def test_list_resource_assignment_display_values_by_ids_batches_resources(monkeypatch):
    assignment_query = query(
        all_=[
            ("1", "Finance"),
            ("1", "Production"),
            ("2", "Education"),
        ]
    )
    _session, context = db_context(assignment_query)
    install_context(monkeypatch, context)

    result = TagManagementDB.list_resource_assignment_display_values_by_ids(
        "tenant-a",
        "agent",
        ["1", "2", "1"],
    )

    assert result == {
        "1": ["Finance", "Production"],
        "2": ["Education"],
    }
    assert ("tenant_id", "tenant-a") in filter_keys(assignment_query)
    assert ("resource_type", "agent") in filter_keys(assignment_query)
    assert ("resource_id", ("1", "2")) in filter_keys(assignment_query)


def test_create_definition_rejects_duplicate_normalization_and_reports_capacity(monkeypatch):
    with pytest.raises(TagManagementConflictError, match="unique after normalization"):
        TagManagementDB.create_definition(
            "tenant-a", 1, "color", "Color", "single_select", [" Red ", "red"], 0, "user-1"
        )

    bucket_query = query(one=record(bucket_id=1, bucket_key="default_resource"))
    definition_count_query = query(count=100)
    _session, context = db_context(bucket_query, definition_count_query)
    install_context(monkeypatch, context)
    with pytest.raises(TagManagementConflictError) as error:
        TagManagementDB.create_definition(
            "tenant-a", 1, "color", "Color", "single_select", ["Red"], 0, "user-1"
        )
    assert error.value.details == {"limit": 100, "current_count": 100, "scope": "definition"}


def test_create_definition_creates_controlled_values_with_normalized_names(monkeypatch):
    bucket_query = query(one=record(bucket_id=1, bucket_key="default_resource"))
    definition_count_query = query(count=0)
    session, context = db_context(bucket_query, definition_count_query)

    def assign_ids():
        for item in session.add.call_args_list:
            if isinstance(item.args[0], TagDefinition):
                item.args[0].definition_id = 9
        for item in session.add_all.call_args_list:
            for value in item.args[0]:
                value.value_id = len(item.args[0])

    session.flush.side_effect = assign_ids
    install_context(monkeypatch, context)
    result = TagManagementDB.create_definition(
        "tenant-a", 1, "color", "Color", "multi_select", [" Red ", "Blue"], 4, "user-1"
    )
    assert result["definition_id"] == 9
    assert result["selection_mode"] == "multi_select"
    assert [value["normalized_value"] for value in result["values"]] == ["red", "blue"]
    assert [value["sort_order"] for value in result["values"]] == [0, 1]
    assert session.query.call_args_list[0]


def test_create_no_value_definition_creates_one_internal_controlled_value(monkeypatch):
    bucket_query = query(one=record(bucket_id=1, bucket_key="default_resource"))
    definition_count_query = query(count=0)
    session, context = db_context(bucket_query, definition_count_query)

    def assign_ids():
        for item in session.add.call_args_list:
            if isinstance(item.args[0], TagDefinition):
                item.args[0].definition_id = 9
        for item in session.add_all.call_args_list:
            for value in item.args[0]:
                value.value_id = 11

    session.flush.side_effect = assign_ids
    install_context(monkeypatch, context)

    result = TagManagementDB.create_definition(
        "tenant-a", 1, "custom_featured", "Featured", "no_value", [], 4, "user-1"
    )

    assert result["selection_mode"] == "no_value"
    assert result["active_value_count"] == 1
    assert result["values"] == [
        {
            "value_id": 11,
            "display_value": "Featured",
            "normalized_value": NO_VALUE_TAG_NORMALIZED_VALUE,
            "sort_order": 0,
            "status": "active",
            "created_by": "user-1",
            "updated_by": "user-1",
            "create_time": None,
            "update_time": None,
        }
    ]


def test_create_definition_without_order_appends_after_existing_definitions(monkeypatch):
    bucket_query = query(one=record(bucket_id=1, bucket_key="default_resource"))
    definition_count_query = query(count=1)
    max_order_query = query()
    max_order_query.scalar.return_value = 4
    session, context = db_context(
        bucket_query,
        definition_count_query,
        max_order_query,
    )

    def assign_ids():
        for item in session.add.call_args_list:
            if isinstance(item.args[0], TagDefinition):
                item.args[0].definition_id = 10
        for item in session.add_all.call_args_list:
            for value in item.args[0]:
                value.value_id = 1

    session.flush.side_effect = assign_ids
    install_context(monkeypatch, context)

    result = TagManagementDB.create_definition(
        "tenant-a", 1, "color", "Color", "single_select", ["Red"], None, "user-1"
    )

    assert result["sort_order"] == 5


def test_create_value_reports_capacity_and_normalizes_display_value(monkeypatch):
    bucket_query = query(one=record(bucket_id=1, bucket_key="default_resource"))
    definition_query = query(one=record(definition_id=9, bucket_id=1, tenant_id="tenant-a"))
    capacity_query = query(count=1000)
    session, context = db_context(bucket_query, definition_query, capacity_query)
    install_context(monkeypatch, context)
    with pytest.raises(TagManagementConflictError) as error:
        TagManagementDB.create_value("tenant-a", 1, 9, "Red", 0, "user-1")
    assert error.value.details == {"limit": 1000, "current_count": 1000, "scope": "value"}

    bucket_query = query(one=record(bucket_id=1, bucket_key="default_resource"))
    definition_query = query(one=record(definition_id=9, bucket_id=1, tenant_id="tenant-a"))
    capacity_query = query(count=0)
    session, context = db_context(bucket_query, definition_query, capacity_query)
    value_id = 12
    session.flush.side_effect = lambda: setattr(session.add.call_args.args[0], "value_id", value_id)
    install_context(monkeypatch, context)
    result = TagManagementDB.create_value("tenant-a", 1, 9, " Red ", 4, "user-1")
    assert result["value_id"] == value_id
    assert result["display_value"] == "Red"
    assert result["normalized_value"] == "red"


def test_definition_rename_preserves_id_and_blocks_multi_to_single_with_assignments(monkeypatch):
    bucket = record(bucket_id=1, bucket_key="default_resource")
    definition = record(
        definition_id=9,
        bucket_id=1,
        tenant_id="tenant-a",
        definition_key="color",
        definition_name="Old",
        selection_mode="multi_select",
        sort_order=0,
    )
    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    assignment_query = query(count=2)
    value_count_query = query(count=3)
    _session, context = db_context(bucket_query, definition_query, assignment_query, value_count_query)
    install_context(monkeypatch, context)
    result, multiple_count = TagManagementDB.update_definition(
        "tenant-a", 1, 9, "New", "single_select", "user-2"
    )
    assert multiple_count == 2
    assert result["definition_id"] == 9
    assert result["definition_name"] == "Old"

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    value_count_query = query(count=3)
    _session, context = db_context(bucket_query, definition_query, value_count_query)
    install_context(monkeypatch, context)
    result, multiple_count = TagManagementDB.update_definition(
        "tenant-a", 1, 9, "New", None, "user-2"
    )
    assert multiple_count == 0
    assert result["definition_id"] == 9
    assert result["definition_name"] == "New"
    assert definition.updated_by == "user-2"


def test_definition_status_order_usage_and_delete_protection(monkeypatch):
    bucket = record(bucket_id=1, bucket_key="default_resource")
    definition = record(
        definition_id=9,
        bucket_id=1,
        tenant_id="tenant-a",
        definition_key="color",
        definition_name="Color",
        selection_mode="single_select",
        sort_order=0,
    )
    for method, args, expected in [
        ("set_definition_status", ("disabled", "user-2"), "disabled"),
        ("set_definition_order", (8, "user-2"), 8),
    ]:
        bucket_query = query(one=bucket)
        definition_query = query(one=definition)
        values_query = query(count=1)
        _session, context = db_context(bucket_query, definition_query, values_query)
        install_context(monkeypatch, context)
        result = getattr(TagManagementDB, method)("tenant-a", 1, 9, *args)
        key = "status" if method.endswith("status") else "sort_order"
        assert result[key] == expected
        assert result["updated_by"] == "user-2"

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    values_query = query(count=4)
    usage_query = query(count=3)
    _session, context = db_context(bucket_query, definition_query, values_query, usage_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.get_definition_usage("tenant-a", 1, 9) == {
        "definition_id": 9,
        "active_value_count": 4,
        "active_usage_count": 3,
        "value_capacity": 1000,
    }

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    values_query = query(count=2)
    usage_query = query(count=1)
    _session, context = db_context(bucket_query, definition_query, values_query, usage_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.delete_definition("tenant-a", 1, 9, "user-2") == {
        "active_value_count": 2,
        "active_usage_count": 1,
    }
    assert definition.delete_flag == "N"

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    values_query = query(count=0)
    usage_query = query(count=0)
    _session, context = db_context(bucket_query, definition_query, values_query, usage_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.delete_definition("tenant-a", 1, 9, "user-2") == {
        "active_value_count": 0,
        "active_usage_count": 0,
    }
    assert definition.delete_flag == "Y"


def test_move_definition_to_top_reindexes_all_active_definitions(monkeypatch):
    bucket = record(bucket_id=1, bucket_key="default_resource")
    first = record(
        definition_id=1,
        bucket_id=1,
        tenant_id="tenant-a",
        definition_key="first",
        definition_name="First",
        selection_mode="single_select",
        sort_order=0,
    )
    target = record(
        definition_id=2,
        bucket_id=1,
        tenant_id="tenant-a",
        definition_key="target",
        definition_name="Target",
        selection_mode="single_select",
        sort_order=1,
    )
    last = record(
        definition_id=3,
        bucket_id=1,
        tenant_id="tenant-a",
        definition_key="last",
        definition_name="Last",
        selection_mode="single_select",
        sort_order=2,
    )
    bucket_query = query(one=bucket)
    definitions_query = query(all_=[first, target, last])
    value_count_query = query(count=2)
    session, context = db_context(
        bucket_query,
        definitions_query,
        value_count_query,
    )
    install_context(monkeypatch, context)

    result = TagManagementDB.move_definition_to_top("tenant-a", 1, 2, "user-2")

    assert [target.sort_order, first.sort_order, last.sort_order] == [0, 1, 2]
    assert {item.updated_by for item in [first, target, last]} == {"user-2"}
    assert result["definition_id"] == 2
    assert result["sort_order"] == 0
    definitions_query.with_for_update.assert_called_once_with()
    session.flush.assert_called_once_with()


def test_value_rename_preserves_id_status_order_usage_and_delete(monkeypatch):
    bucket = record(bucket_id=1, bucket_key="default_resource")
    definition = record(definition_id=9, bucket_id=1, tenant_id="tenant-a")
    value = record(
        value_id=11,
        definition_id=9,
        tenant_id="tenant-a",
        display_value="Old",
        normalized_value="old",
        sort_order=0,
    )

    def run_value_action(method, action_args, query_result, expected_key, expected):
        bucket_query = query(one=bucket)
        definition_query = query(one=definition)
        value_query = query(one=value)
        extra_query = query(count=query_result) if query_result is not None else None
        queries = [bucket_query, definition_query, value_query]
        if extra_query is not None:
            queries.append(extra_query)
        _session, context = db_context(*queries)
        install_context(monkeypatch, context)
        result = getattr(TagManagementDB, method)("tenant-a", 1, 9, 11, *action_args)
        assert result[expected_key] == expected
        assert result["value_id"] == 11
        return result

    result = run_value_action("update_value", (" New ", "user-2"), None, "normalized_value", "new")
    assert result["display_value"] == "New"
    assert value.updated_by == "user-2"
    assert run_value_action("set_value_status", ("disabled", "user-2"), None, "status", "disabled")
    assert run_value_action("set_value_order", (8, "user-2"), None, "sort_order", 8)

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    value_query = query(one=value)
    usage_query = query(count=2)
    _session, context = db_context(bucket_query, definition_query, value_query, usage_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.get_value_usage("tenant-a", 1, 9, 11) == {
        "value_id": 11,
        "active_usage_count": 2,
    }

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    value_query = query(one=value)
    usage_query = query(count=2)
    _session, context = db_context(bucket_query, definition_query, value_query, usage_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.delete_value("tenant-a", 1, 9, 11, "user-2") == 2

    bucket_query = query(one=bucket)
    definition_query = query(one=definition)
    value_query = query(one=value)
    usage_query = query(count=0)
    _session, context = db_context(bucket_query, definition_query, value_query, usage_query)
    install_context(monkeypatch, context)
    assert TagManagementDB.delete_value("tenant-a", 1, 9, 11, "user-2") == 0
    assert value.delete_flag == "Y"


def test_count_resource_assignments_by_ids_groups_tenant_scoped_counts(monkeypatch):
    item = MagicMock(name="count_query")
    item.filter.return_value = item
    item.group_by.return_value = item
    item.all.return_value = [("resource-a", 3), ("resource-b", 1)]
    session, context = db_context(item)
    install_context(monkeypatch, context)

    counts = TagManagementDB.count_resource_assignments_by_ids(
        "tenant-a", "knowledge_document", ["resource-a", "resource-b", "resource-a"]
    )

    assert counts == {"resource-a": 3, "resource-b": 1}
    assert ("tenant_id", "tenant-a") in filter_keys(item)

    counts = TagManagementDB.count_resource_assignments_by_ids(
        "tenant-a", "knowledge_document", []
    )
    assert counts == {}


def test_filter_authorized_resource_ids_applies_and_semantics_with_short_circuit(monkeypatch):
    first = query(all_=[("doc-b",)])
    second = query(all_=[("doc-b",)])
    session, context = db_context(first, second)
    install_context(monkeypatch, context)

    filters = [
        SimpleNamespace(definition_id=11, value_ids=[21]),
        SimpleNamespace(definition_id=12, value_ids=[31]),
    ]
    result = TagManagementDB.filter_authorized_resource_ids(
        "tenant-a", "knowledge_document", ["doc-a", "doc-b"], filters
    )
    assert result == ["doc-b"]

    # First predicate matches nothing: short circuit, second query never runs.
    none_query = query(all_=[])
    session, context = db_context(none_query)
    install_context(monkeypatch, context)
    result = TagManagementDB.filter_authorized_resource_ids(
        "tenant-a", "knowledge_document", ["doc-a"], filters[:1]
    )
    assert result == []


def test_filter_authorized_resource_ids_returns_ids_when_no_filters(monkeypatch):
    session, context = db_context()
    install_context(monkeypatch, context)
    assert TagManagementDB.filter_authorized_resource_ids(
        "tenant-a", "knowledge_document", ["doc-a", "doc-a"], []
    ) == ["doc-a"]


def test_soft_delete_resource_assignments_marks_tenant_scoped_rows(monkeypatch):
    item = MagicMock(name="delete_query")
    item.filter.return_value = item
    item.update.return_value = 2
    session, context = db_context(item)
    install_context(monkeypatch, context)

    count = TagManagementDB.soft_delete_resource_assignments(
        "tenant-a", "knowledge_document", "resource-x", "user-1"
    )
    assert count == 2
    assert ("tenant_id", "tenant-a") in filter_keys(item)
    update_call = item.update.call_args
    assert update_call.kwargs["synchronize_session"] is False
    values = update_call.args[0]
    keys = {getattr(key, "key", str(key)) for key in values}
    assert "delete_flag" in keys
    assert "updated_by" in keys
    assert values[ResourceTagAssignment.delete_flag] == "Y"
    assert values[ResourceTagAssignment.updated_by] == "user-1"
