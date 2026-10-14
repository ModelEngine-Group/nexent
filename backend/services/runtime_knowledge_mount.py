"""Request-local knowledge tool binding; never updates database records."""
from copy import deepcopy
from math import isfinite

from consts.const import ENABLE_AIDP_KNOWLEDGE
from consts.exceptions import ValidationError
from database.tool_db import query_all_tools

MANAGED_CLASSES = {"KnowledgeBaseSearchTool", "AidpSearchTool"}
RESERVED = {"index_names", "kds_list", "display_names", "server_url", "api_key", "tenant_id",
            "observer", "kds_name_to_id_map", "allowed_kds_set", "allowed_index_names"}


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
    fields = {p["name"]: p for p in tool.get("params") or []}
    for name, value in (scope.retrieval_config or {}).items():
        if name in RESERVED or name not in fields:
            raise ValidationError(f"Unsupported knowledge parameter: {name}")
        field_type = fields[name].get("type")
        expected = {"string": str, "number": (int, float), "integer": int,
                    "boolean": bool, "array": list, "object": dict}.get(field_type)
        if expected and (not isinstance(value, expected) or (
            field_type in {"number", "integer"} and (isinstance(value, bool) or not isfinite(value))
        )):
            raise ValidationError(f"Invalid knowledge parameter: {name}")
        choices = {"search_mode": {"hybrid", "accurate", "semantic"},
                   "search_method": {"hybrid_search", "vector_search", "full_text_search"},
                   "rerank_mode": {"performance", "high_accuracy"},
                   "reranking_mode": {"performance", "high_accuracy"}}
        if name in choices and value not in choices[name]:
            raise ValidationError(f"Invalid knowledge parameter: {name}")
        fields[name]["default"] = deepcopy(value)
    tool["params"] = list(fields.values())
    return [*result, tool]
