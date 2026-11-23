# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Batch tag projections preserve the resource catalog authorization boundary."""

from management.services.tag.projection import (
    TagManagementDB,
    project_authorized_document_tags,
    project_authorized_resource_tags,
)
from management.services.tag.resources import _encode_document_resource_id


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


def _document_resource_id(path: str) -> str:
    return _encode_document_resource_id("local", "kb-index", path)


def test_document_projection_batches_paths_once_and_drops_internal_fields(mocker):
    mocker.patch(
        "management.services.tag.projection.get_knowledge_record",
        return_value={"index_name": "kb-index", "tenant_id": "tenant"},
    )
    resources = [
        {"path_or_url": "knowledge_base/a.txt", "file": "a.txt"},
        {"path_or_url": "knowledge_base/a.txt", "file": "a.txt (duplicate)"},
        {"file": "lifecycle-only.txt"},
    ]
    first_id = _document_resource_id("knowledge_base/a.txt")
    lookup = mocker.patch.object(
        TagManagementDB,
        "list_resource_assignments_batch",
        return_value={
            first_id: [
                {
                    "definition_id": 1,
                    "definition_key": "domain",
                    "definition_name": "Domain",
                    "selection_mode": "multi_select",
                    "value_id": 2,
                    "display_value": "Finance",
                    "value_status": "active",
                    "tenant_id": "tenant",
                }
            ]
        },
    )

    result = project_authorized_document_tags(
        resources, index_name="kb-index", tenant_id="tenant"
    )

    lookup.assert_called_once_with(
        "tenant", "knowledge_document", [first_id], "knowledge_content"
    )
    assert result[0]["tags"] == [
        {
            "definition_id": 1,
            "definition_key": "domain",
            "definition_name": "Domain",
            "selection_mode": "multi_select",
            "value_id": 2,
            "display_value": "Finance",
            "value_status": "active",
        }
    ]
    assert result[1]["tags"] == result[0]["tags"]
    assert result[2]["tags"] == []


def test_document_projection_chunks_resource_ids_at_500(mocker):
    mocker.patch(
        "management.services.tag.projection.get_knowledge_record",
        return_value={"index_name": "kb-index", "tenant_id": "tenant"},
    )
    lookup = mocker.patch.object(
        TagManagementDB, "list_resource_assignments_batch", return_value={}
    )
    resources = [
        {"path_or_url": f"knowledge_base/file-{index}.txt"}
        for index in range(501)
    ]

    result = project_authorized_document_tags(
        resources, index_name="kb-index", tenant_id="tenant"
    )

    assert [len(call.args[2]) for call in lookup.call_args_list] == [500, 1]
    assert all(file["tags"] == [] for file in result)


def test_document_projection_skips_lookup_for_empty_or_ownerless_lists(mocker):
    parent = mocker.patch("management.services.tag.projection.get_knowledge_record")
    lookup = mocker.patch.object(
        TagManagementDB, "list_resource_assignments_batch"
    )

    assert project_authorized_document_tags(
        [], index_name="kb-index", tenant_id="tenant"
    ) == []
    assert project_authorized_document_tags(
        [{"file": "no-path.txt"}], index_name="kb-index", tenant_id="tenant"
    ) == [{"file": "no-path.txt", "tags": []}]
    parent.assert_not_called()
    lookup.assert_not_called()


def test_document_projection_keeps_tags_empty_for_another_tenant(mocker):
    mocker.patch(
        "management.services.tag.projection.get_knowledge_record",
        return_value={"index_name": "kb-index", "tenant_id": "owner"},
    )
    lookup = mocker.patch.object(
        TagManagementDB, "list_resource_assignments_batch"
    )

    result = project_authorized_document_tags(
        [{"path_or_url": "knowledge_base/a.txt"}],
        index_name="kb-index",
        tenant_id="tenant",
    )

    assert result[0]["tags"] == []
    lookup.assert_not_called()


def test_document_projection_degrades_to_empty_tags_on_lookup_failure(mocker):
    mocker.patch(
        "management.services.tag.projection.get_knowledge_record",
        return_value={"index_name": "kb-index", "tenant_id": "tenant"},
    )
    mocker.patch.object(
        TagManagementDB,
        "list_resource_assignments_batch",
        side_effect=RuntimeError("tag tables unavailable"),
    )

    result = project_authorized_document_tags(
        [{"path_or_url": "knowledge_base/a.txt"}],
        index_name="kb-index",
        tenant_id="tenant",
    )

    assert result == [{"path_or_url": "knowledge_base/a.txt", "tags": []}]
