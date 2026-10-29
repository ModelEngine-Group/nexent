# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One-time legacy LLM snapshot construction; database ownership stays in the DAL."""

from copy import deepcopy

from contracts.errors.exceptions import ModelOutletValidationError
from contracts.model import ModelProfilePreviewRequest
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.model_service.compatibility.legacy_config import legacy_agent_request_parameters, legacy_thinking_enabled
from nexent.core.model_service.profiles.outlet_storage import decode_resolved_model_profile, encode_resolved_model_profile
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.registry import model_service_references
from pydantic import ValidationError
from management.services.model.profiles import build_outlet_draft
from management.services.model.names import add_repo_to_name

MIGRATION_VERSION = "legacy_llm_outlet_v2"


def _pointer(key):
    return key.replace("~", "~0").replace("/", "~1")


def _leaves(value, prefix=""):
    for key, child in value.items():
        path = prefix + "/" + _pointer(key)
        if isinstance(child, dict) and child:
            yield from _leaves(child, path)
        else:
            yield path, child


def _rule(key, value, path=None, transform="identity_v1"):
    schema = {"type": {bool: "boolean", int: "integer", float: "number", str: "string",
                       list: "array", dict: "object", type(None): "null"}[type(value)]}
    # Sampling NULL is an explicit provider default, not a missing stored key.
    if key in {"temperature", "top_p"}:
        schema = {"type": ["number", "null"]}
    result = {"key": key, "schema": schema, "visible": path is not None,
              "editable": path is not None, "required": False, "allowed_scopes": ["outlet", "conversation"],
              "ui_group": "reasoning" if key.startswith("reasoning") or key == "enable_thinking" else "advanced",
              "owner": "combination", "source": {"ref": MIGRATION_VERSION, "version": 1}}
    if path is not None:
        result["api_binding"] = {"path": path, "transform_ref": transform, "transform_version": 1}
    return result


def _parameters(profile, body, legacy_extra):
    mapped = {"/temperature": "temperature", "/top_p": "top_p", "/max_tokens": "max_output_tokens",
              "/reasoning_effort": "reasoning_effort", "/thinking_budget": "reasoning_budget_tokens",
              "/thinking/budget_tokens": "reasoning_budget_tokens", "/enable_thinking": "enable_thinking",
              "/chat_template_kwargs/enable_thinking": "enable_thinking", "/thinking/type": "enable_thinking"}
    rules, values, extras = {}, {}, []
    for path, value in _leaves(body):
        key = mapped.get(path)
        if key is None:
            extras.append({"path": path, "value": value})
            continue
        if key in values:
            raise ModelOutletValidationError(category="LEGACY_PARAMETER_BINDING_CONFLICT", path=key)
        transform = "identity_v1"
        if path == "/thinking/type":
            if value not in ("enabled", "disabled"):
                raise ModelOutletValidationError(category="LEGACY_THINKING_FORMAT_INVALID", path=key)
            value = value == "enabled"
            transform = "thinking_toggle_v1"
        values[key], rules[key] = value, _rule(key, value, path, transform)
    unbound = []
    for key in ("enable_thinking", "reasoning_effort", "reasoning_budget_tokens"):
        if key not in values and key in legacy_extra:
            values[key], rules[key] = legacy_extra[key], _rule(key, legacy_extra[key])
            unbound.append(key)
    # Keep unconfigured runtime-option declarations without introducing new defaults.
    for declaration in profile.parameter_rules:
        key = declaration["key"]
        if key not in rules:
            declaration = deepcopy(declaration)
            for field in ("default_value", "fixed_value", "condition"):
                declaration.pop(field, None)
            declaration["required"] = False
            rules[key] = declaration
    if "max_output_tokens" not in rules and "max_tokens" not in rules:
        declaration = _rule("max_output_tokens", 1, "/max_tokens")
        declaration["schema"]["minimum"] = 1
        rules["max_output_tokens"] = declaration
    if "stop" not in rules:
        declaration = _rule("stop", [], "/stop")
        declaration.update(visible=False, allowed_scopes=["outlet"], ui_group="runtime")
        declaration["schema"] = {"type": ["string", "array"], "items": {"type": "string"}}
        rules["stop"] = declaration
    if "response_format" not in rules:
        declaration = _rule("response_format", {}, "/response_format")
        declaration.update(visible=False, allowed_scopes=["outlet"], ui_group="runtime")
        rules["response_format"] = declaration
    return list(rules.values()), values, extras, unbound


def build_legacy_outlet_snapshot(row, *, legacy_capability, migrated_at, from_version="pre-profile"):
    """Preserve effective legacy values and references; never read current TOML for saved rows."""
    refs = model_service_references()
    if row.get("profile_schema_version") is not None:
        return decode_resolved_model_profile(row, registered_references=refs)
    if row.get("model_type") not in {"llm", "chat"}:
        raise ModelOutletValidationError(category="LEGACY_MODEL_TYPE_UNSUPPORTED")
    try:
        name = add_repo_to_name(row.get("model_repo") or "", row["model_name"])
        request = ModelProfilePreviewRequest(request_model_id=name, display_name=row.get("display_name") or name,
            authentication_scheme="bearer_token_v1" if row.get("api_key") else "no_auth_v1",
            provider_info={"base_url": row["base_url"], "provider_id": row.get("model_factory") or "custom",
                "ssl_verify": row.get("ssl_verify") if row.get("ssl_verify") is not None else True,
                "timeout_seconds": row.get("timeout_seconds") or 60,
                "concurrency_limit": row.get("concurrency_limit")})
        profile, _ = build_outlet_draft(request, row["tenant_id"])
        body = legacy_agent_request_parameters(row, model_id=name, capability=legacy_capability)
        old = ModelConfig(cite_name=request.display_name, model_name=name, url=row["base_url"],
            max_tokens=row.get("max_tokens"), max_output_tokens=row.get("max_output_tokens"),
            context_window_tokens=row.get("context_window_tokens"))
        if row.get("default_output_reserve_tokens") is not None:
            # The legacy W2 budget supplied this value to the actual model request.
            body["max_tokens"] = row["default_output_reserve_tokens"]
        elif old.max_output_tokens is not None:
            body.setdefault("max_tokens", old.max_output_tokens)
        data = profile.model_dump(mode="json")
        rules, values, extras, unbound = _parameters(profile, body, row.get("extra_params") or {})
        data.update(outlet_id=row["model_id"], config_revision=row.get("config_revision") or 1,
                    parameter_rules=rules, parameter_values=values, extra_api_parameters=extras)
        data["connection"]["credential_ref"]["model_id"] = row["model_id"]
        defaults = []
        context = data["capabilities"]["context"]
        for field, column in (("combined_window", "context_window_tokens"), ("input_limit", "max_input_tokens"),
                              ("output_limit", "max_output_tokens")):
            if row.get(column) is not None:
                context[field] = row[column]
        if context["combined_window"] is None:
            context["combined_window"] = 200000
            defaults.append("capabilities.context.combined_window")
        for field in ("input_limit", "output_limit"):
            if row.get({"input_limit": "max_input_tokens", "output_limit": "max_output_tokens"}[field]) is None:
                if context[field] is not None and context[field] > context["combined_window"]:
                    context[field] = None
        for field, column in (("output_reserve_tokens", "default_output_reserve_tokens"),
            ("tokenizer_family", "tokenizer_family"), ("capacity_source", "capacity_source"),
            ("capability_profile_version", "capability_profile_version")):
            data["context_configuration"][field] = row.get(column)
        controls = []
        if "enable_thinking" in values:
            controls.append({"mode": "toggle", "parameter_key": "enable_thinking", "values": [False, True]})
        if "reasoning_effort" in values:
            controls.append({"mode": "effort", "parameter_key": "reasoning_effort", "values": [values["reasoning_effort"]]})
        if type(values.get("reasoning_budget_tokens")) is int:
            value = values["reasoning_budget_tokens"]
            controls.append({"mode": "budget_tokens", "parameter_key": "reasoning_budget_tokens", "min": 0,
                             "max": None, "special_values": [value] if value < 0 else []})
        reasoning = data["capabilities"]["reasoning"]
        declared_reasoning = row.get("reasoning_supported")
        enabled_legacy = legacy_thinking_enabled(row.get("extra_params"))
        if declared_reasoning is True or (declared_reasoning is None and enabled_legacy):
            reasoning.update(status="supported", controls=controls or reasoning["controls"])
        elif declared_reasoning is False:
            reasoning.update(status="unsupported", controls=None, response_paths=[])
        elif reasoning["status"] == "unknown":
            reasoning.update(status="unsupported", controls=None, response_paths=[])
            defaults.append("capabilities.reasoning.status")
        if reasoning["status"] == "supported" and controls:
            reasoning["controls"] = controls
        if reasoning["controls"] is not None:
            reasoning["controls"] = [control for control in reasoning["controls"]
                if not (control["parameter_key"] in unbound and values.get(control["parameter_key"]) is None)]
        tools = data["capabilities"]["tools"]
        if row.get("native_tool_call_supported") is not None:
            tools["status"] = "supported" if row["native_tool_call_supported"] else "unsupported"
        elif tools["status"] == "unknown":
            tools["status"] = "unsupported"
            defaults.append("capabilities.tools.status")
        data["provenance"]["provider_metadata"]["migration"] = {
            "origin": "legacy_model_record", "from_version": from_version, "version": MIGRATION_VERSION,
            "migrated_at": migrated_at, "reviewed_revision": None, "defaulted_fields": defaults,
            "unmatched_atoms": [kind for kind, key in (("model", profile.model_profile_key),
                                                      ("provider", profile.provider_key)) if key is None],
            "unbound_legacy_parameters": unbound,
        }
        resolved = ResolvedModelProfile.model_validate(data)
        encode_resolved_model_profile(resolved, registered_references=refs,
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
        return resolved
    except ModelOutletValidationError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ModelOutletValidationError(category="LEGACY_OUTLET_INVALID") from None


def migrate_legacy_outlets(*, dry_run=False, batch_size=100):
    """Process each legacy LLM once per invocation, retaining sanitized failure diagnostics."""
    from datetime import datetime, timezone

    from configs.model_catalog_loader import resolve_reasoning_capability
    from management.db.model.outlets import migrate_legacy_model_records

    migrated_at = datetime.now(timezone.utc).isoformat()

    def construct(record):
        name = add_repo_to_name(record.get("model_repo") or "", record["model_name"])
        capability = resolve_reasoning_capability(name, record.get("base_url"), record.get("model_factory"),
                                                  allow_gateway_fallback=False)
        return build_legacy_outlet_snapshot(record, legacy_capability=capability, migrated_at=migrated_at)

    results = []
    cursor = 0
    while True:
        batch = migrate_legacy_model_records(construct, registered_references=model_service_references(),
            batch_size=batch_size, after_model_id=cursor, dry_run=dry_run)
        if not batch:
            break
        results.extend(batch)
        cursor = max(item["model_id"] for item in batch)
    return {"migration_version": MIGRATION_VERSION, "dry_run": dry_run,
            "migrated": sum(item["status"] == "migrated" for item in results),
            "ready": sum(item["status"] == "ready" for item in results),
            "failed": sum(item["status"] == "failed" for item in results), "items": results}
