# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Initialize unified tags for newly registered built-in search tools."""

from management.db.models import ResourceTagAssignment, TagDefinition, TagValue
from management.db.tag.repository import TagManagementDB


def initialize_search_tool_tags(session, tenant_id: str, tool_id: int, actor_id: str) -> None:
    """Assign Keywords=search once, within the tool registration transaction."""
    binding = TagManagementDB._get_active_resource_binding(
        session, tenant_id, "tool", "default_resource", for_update=True,
    )
    definition = session.query(TagDefinition).filter(
        TagDefinition.tenant_id == tenant_id,
        TagDefinition.bucket_id == binding.bucket_id,
        TagDefinition.definition_key == "keywords",
        TagDefinition.delete_flag == "N",
    ).one_or_none()
    if definition is None:
        definition = TagDefinition(
            tenant_id=tenant_id, bucket_id=binding.bucket_id,
            definition_key="keywords", definition_name="Keywords",
            selection_mode="multi_select", sort_order=0, status="active", delete_flag="N",
            created_by=actor_id, updated_by=actor_id,
        )
        session.add(definition)
        session.flush()
    if definition.status != "active" or definition.selection_mode != "multi_select":
        return
    value = session.query(TagValue).filter(
        TagValue.tenant_id == tenant_id,
        TagValue.definition_id == definition.definition_id,
        TagValue.normalized_value == "search",
        TagValue.delete_flag == "N",
    ).one_or_none()
    if value is None:
        value = TagValue(
            tenant_id=tenant_id, definition_id=definition.definition_id,
            display_value="search", normalized_value="search", sort_order=0,
            status="active", delete_flag="N", created_by=actor_id, updated_by=actor_id,
        )
        session.add(value)
        session.flush()
    if value.status != "active":
        return
    existing = session.query(ResourceTagAssignment).filter(
        ResourceTagAssignment.tenant_id == tenant_id,
        ResourceTagAssignment.resource_type == "tool",
        ResourceTagAssignment.resource_id == str(tool_id),
        ResourceTagAssignment.value_id == value.value_id,
    ).one_or_none()
    if existing is None:
        session.add(ResourceTagAssignment(
            tenant_id=tenant_id, resource_type="tool", resource_id=str(tool_id),
            definition_id=definition.definition_id, value_id=value.value_id,
            status="active", delete_flag="N", created_by=actor_id, updated_by=actor_id,
        ))
