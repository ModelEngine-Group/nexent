"""Build and compare prompt, context-item, resource, and tool parity snapshots."""

from __future__ import annotations

import json
from typing import Any

from .experiment_manifest import _jsonable, sha256_value


PROMPT_COMPONENT_IDS = {
    "basic_information": "system:header",
    "duty_prompt": "system:duty",
    "constraint_prompt": "system:constraint",
    "execution_prompt": "system:execution_flow",
    "resource_prompt": "system:available_resources_header",
    "code_rules_prompt": "system:code_norms",
}
RESOURCE_TYPES = {
    "tools": "tool",
    "skills": "skill",
    "managed_agents": "managed_agent",
    "external_agents": "external_agent",
    "memory": "memory",
    "knowledge_base": "knowledge_base",
}
TOOL_SCHEMA_FIELDS = (
    "class_name",
    "name",
    "description",
    "inputs",
    "output_type",
    "params",
    "source",
    "usage",
    "labels",
)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def canonical_tool_schema(tool: Any) -> dict[str, Any]:
    """Return the model-visible schema plus a non-secret implementation identifier."""
    schema = {
        field: _jsonable(_field(tool, field))
        for field in TOOL_SCHEMA_FIELDS
        if _field(tool, field) is not None
    }
    if isinstance(schema.get("inputs"), str):
        try:
            schema["inputs"] = json.loads(schema["inputs"])
        except (TypeError, ValueError):
            # Preserve invalid/non-JSON schemas verbatim so parity fails visibly.
            pass
    class_name = str(schema.get("class_name") or type(tool).__name__)
    source = str(schema.get("source") or "local")
    metadata = _field(tool, "metadata", {}) or {}
    runtime_scope = (
        {
            key: metadata.get(key)
            for key in ("agent_id", "tenant_id", "version_no")
        }
        if isinstance(metadata, dict)
        and metadata.get("_benchmark_assembly_origin") == "injected_builtin"
        else {}
    )
    return {
        **schema,
        "assembly_origin": (
            metadata.get("_benchmark_assembly_origin", "configured")
            if isinstance(metadata, dict)
            else "configured"
        ),
        "implementation": {
            "class_name": class_name,
            "source": source,
            "version": str(_field(tool, "version", "") or ""),
            "runtime_scope": runtime_scope,
        },
        "schema_hash": sha256_value(schema),
    }


def build_tool_snapshot(tools: list[Any]) -> dict[str, Any]:
    schemas = [canonical_tool_schema(tool) for tool in tools]
    return {
        "count": len(schemas),
        "ordered_names": [str(tool.get("name", "")) for tool in schemas],
        "schemas": schemas,
        "schema_hash": sha256_value(schemas),
    }


def build_context_item_snapshot(context_items: list[Any]) -> list[dict[str, Any]]:
    """Preserve the exact pre-compaction assembly order and policy attributes."""
    normalized_items = list(context_items)
    try:
        from nexent.core.agents.context.models import ContextItem, ContextItemInput

        normalized_items = [
            ContextItem.from_input(item) if isinstance(item, ContextItemInput) else item
            for item in normalized_items
        ]
        normalized_items.sort(
            key=lambda item: getattr(item, "layout_key", (999, 0, 0, str(_field(item, "id", ""))))
        )
    except ImportError:
        pass
    snapshot = []
    for position, item in enumerate(normalized_items):
        item_type = _field(item, "type", "unknown")
        item_type = str(getattr(item_type, "value", item_type))
        content = _jsonable(_field(item, "content", {}))
        metadata = _jsonable(_field(item, "metadata", {}))
        snapshot.append({
            "position": position,
            "id": str(_field(item, "id", "")),
            "type": item_type,
            "content": content,
            "content_hash": sha256_value(content),
            "source": list(_field(item, "source", ()) or ()),
            "priority": int(_field(item, "priority", 0) or 0),
            "required": bool(_field(item, "required", False)),
            "classification": (
                "stable"
                if item_type in {
                    "system", "system_prompt", "tool", "skill",
                    "managed_agent", "external_agent",
                }
                else "dynamic"
            ),
            "metadata": metadata,
        })
    return snapshot


def build_prompt_snapshot(
    context_items: list[Any],
    prompt_templates: dict[str, Any],
    *,
    language: str,
    template_version: str,
    template_source: str,
) -> dict[str, Any]:
    by_id = {str(_field(item, "id", "")): _field(item, "content", {}) for item in context_items}
    components: dict[str, dict[str, Any]] = {}
    for name, item_id in PROMPT_COMPONENT_IDS.items():
        content = by_id.get(item_id, {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)
        components[name] = {
            "source_item_id": item_id,
            "content": text,
            "hash": sha256_value(text),
        }
    final_contract = _jsonable((prompt_templates or {}).get("final_answer", {}))
    components["final_answer_contract"] = {
        "source_item_id": "prompt_templates.final_answer",
        "content": final_contract,
        "hash": sha256_value(final_contract),
    }
    return {
        "language": language,
        "prompt_template_version": str(template_version),
        "template_source": template_source,
        "components": components,
        "component_hashes": {
            f"{name}_hash": component["hash"] for name, component in components.items()
        },
    }


def build_resource_snapshot(
    context_items: list[Any],
    *,
    supported: dict[str, bool] | None = None,
    intentional_empty: dict[str, bool] | None = None,
) -> dict[str, Any]:
    supported = supported or {}
    intentional_empty = intentional_empty or {}
    item_types = [str(getattr(_field(item, "type", ""), "value", _field(item, "type", ""))) for item in context_items]
    resources = {}
    for resource, item_type in RESOURCE_TYPES.items():
        count = item_types.count(item_type)
        is_supported = supported.get(resource, True)
        resources[resource] = {
            "count": count,
            "status": (
                "present" if count else "intentional_empty"
                if intentional_empty.get(resource, False) else "empty"
                if is_supported else "unsupported"
            ),
            "supported": is_supported,
            "schema_hash": sha256_value([
                _jsonable(_field(item, "content", {}))
                for item in context_items
                if str(getattr(_field(item, "type", ""), "value", _field(item, "type", ""))) == item_type
            ]),
        }
    return resources


def build_parity_snapshot(
    *,
    context_items: list[Any],
    prompt_templates: dict[str, Any],
    tools: list[Any],
    language: str,
    template_version: str,
    template_source: str,
    resource_support: dict[str, bool] | None = None,
    intentional_empty_resources: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_schema_version": 1,
        "prompt": build_prompt_snapshot(
            context_items,
            prompt_templates,
            language=language,
            template_version=template_version,
            template_source=template_source,
        ),
        "context_items": build_context_item_snapshot(context_items),
        "resources": build_resource_snapshot(
            context_items,
            supported=resource_support,
            intentional_empty=intentional_empty_resources,
        ),
        "tools": build_tool_snapshot(tools),
    }


def diff_parity_snapshots(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_items = expected.get("context_items", [])
    actual_items = actual.get("context_items", [])
    expected_by_id = {item["id"]: item for item in expected_items}
    actual_by_id = {item["id"]: item for item in actual_items}
    shared_ids = expected_by_id.keys() & actual_by_id.keys()

    expected_tools = expected.get("tools", {}).get("schemas", [])
    actual_tools = actual.get("tools", {}).get("schemas", [])
    expected_tool_map = {tool.get("name"): tool for tool in expected_tools}
    actual_tool_map = {tool.get("name"): tool for tool in actual_tools}
    shared_tools = expected_tool_map.keys() & actual_tool_map.keys()

    prompt_expected = expected.get("prompt", {})
    prompt_actual = actual.get("prompt", {})
    expected_hashes = prompt_expected.get("component_hashes", {})
    actual_hashes = prompt_actual.get("component_hashes", {})
    prompt_mismatches = sorted(
        key for key in expected_hashes.keys() | actual_hashes.keys()
        if expected_hashes.get(key) != actual_hashes.get(key)
    )
    resource_mismatches = sorted(
        name for name in expected.get("resources", {}).keys() | actual.get("resources", {}).keys()
        if expected.get("resources", {}).get(name) != actual.get("resources", {}).get(name)
    )
    diff = {
        "prompt_component_mismatches": prompt_mismatches,
        "language_mismatch": prompt_expected.get("language") != prompt_actual.get("language"),
        "template_version_mismatch": (
            prompt_expected.get("prompt_template_version")
            != prompt_actual.get("prompt_template_version")
        ),
        "missing_items": sorted(expected_by_id.keys() - actual_by_id.keys()),
        "unexpected_items": sorted(actual_by_id.keys() - expected_by_id.keys()),
        "content_hash_mismatches": sorted(
            item_id for item_id in shared_ids
            if expected_by_id[item_id].get("content_hash") != actual_by_id[item_id].get("content_hash")
        ),
        "ordering_mismatches": sorted(
            item_id for item_id in shared_ids
            if expected_by_id[item_id].get("position") != actual_by_id[item_id].get("position")
        ),
        "priority_mismatches": sorted(
            item_id for item_id in shared_ids
            if expected_by_id[item_id].get("priority") != actual_by_id[item_id].get("priority")
        ),
        "required_flag_mismatches": sorted(
            item_id for item_id in shared_ids
            if expected_by_id[item_id].get("required") != actual_by_id[item_id].get("required")
        ),
        "resource_mismatches": resource_mismatches,
        "missing_tools": sorted(expected_tool_map.keys() - actual_tool_map.keys()),
        "unexpected_tools": sorted(actual_tool_map.keys() - expected_tool_map.keys()),
        "tool_order_mismatch": (
            expected.get("tools", {}).get("ordered_names", [])
            != actual.get("tools", {}).get("ordered_names", [])
        ),
        "tool_schema_mismatches": sorted(
            name for name in shared_tools
            if expected_tool_map[name].get("schema_hash") != actual_tool_map[name].get("schema_hash")
        ),
        "tool_assembly_origin_mismatches": sorted(
            name for name in shared_tools
            if expected_tool_map[name].get("assembly_origin")
            != actual_tool_map[name].get("assembly_origin")
        ),
        "tool_implementation_mismatches": sorted(
            name for name in shared_tools
            if expected_tool_map[name].get("implementation") != actual_tool_map[name].get("implementation")
        ),
    }
    diff["passed"] = not any(
        value for key, value in diff.items() if key != "passed"
    )
    return diff
