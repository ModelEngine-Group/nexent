"""Batch tag projections preserve the resource catalog authorization boundary."""

from services.resource_tag_projection import project_authorized_resource_tags, TagManagementDB


def test_tag_projection_batches_authorized_ids_and_never_expands_resources(mocker):
    lookup = mocker.patch.object(TagManagementDB, "list_resource_assignment_display_values_by_ids", return_value={"1": ["Finance", "Finance", "Search"], "2": ["Legal"], "secret": ["Private"]})
    resources = [{"knowledge_id": 1}, {"knowledge_id": 2}]
    result = project_authorized_resource_tags(resources, resource_type="knowledge_base", id_field="knowledge_id", default_tenant_id="tenant")
    lookup.assert_called_once_with("tenant", "knowledge_base", ["1", "2"])
    assert result == [{"knowledge_id": 1, "tags": ["Finance", "Search"]}, {"knowledge_id": 2, "tags": ["Legal"]}]
    assert resources == [{"knowledge_id": 1}, {"knowledge_id": 2}]


def test_tag_projection_keeps_shared_resource_tenants_separate(mocker):
    lookup = mocker.patch.object(TagManagementDB, "list_resource_assignment_display_values_by_ids", side_effect=[{"1": ["Local"]}, {"1": ["Shared"]}])
    result = project_authorized_resource_tags([{"knowledge_id": 1}, {"knowledge_id": 1, "tenant_id": "owner"}], resource_type="knowledge_base", id_field="knowledge_id", default_tenant_id="tenant")
    assert [item["tags"] for item in result] == [["Local"], ["Shared"]]
    assert lookup.call_count == 2


def test_empty_authorized_list_does_not_query_tag_assignments(mocker):
    lookup = mocker.patch.object(TagManagementDB, "list_resource_assignment_display_values_by_ids")
    assert project_authorized_resource_tags([], resource_type="knowledge_base", id_field="knowledge_id", default_tenant_id="tenant") == []
    lookup.assert_not_called()
