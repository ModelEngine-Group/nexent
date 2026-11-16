# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Request-local knowledge tool binding; never updates database records."""
from copy import deepcopy

from contracts.constants.environment import ENABLE_AIDP_KNOWLEDGE
from contracts.errors.exceptions import ValidationError
from management.db.tool.repository import query_all_tools

MANAGED_CLASSES = {"KnowledgeBaseSearchTool", "AidpSearchTool"}


def mount_knowledge_records(records, scope, tenant_id):
    """Return an isolated root tool list, preserving unrelated tools."""
    records = deepcopy(records)
    if scope is None:
        return records
    source = "aidp" if ENABLE_AIDP_KNOWLEDGE else "local"
    other = scope.local if source == "aidp" else scope.aidp
    if other.mode == "override":
        raise ValidationError("Knowledge source changed; reselect knowledge bases")
    selection = getattr(scope, source)
    kind = "AidpSearchTool" if source == "aidp" else "KnowledgeBaseSearchTool"
    tool = next((t for t in records if t.get("class_name") == kind), None)
    result = [t for t in records if t.get("class_name") not in MANAGED_CLASSES]
    if selection.mode == "disabled" or (selection.mode == "inherit" and tool is None):
        return result
    if tool is None:
        tool = next((deepcopy(t) for t in query_all_tools(tenant_id)
                     if t.get("class_name") == kind and t.get("is_available") is True), None)
    if tool is None:
        raise ValidationError("Managed knowledge tool is unavailable")
    return [*result, tool]
