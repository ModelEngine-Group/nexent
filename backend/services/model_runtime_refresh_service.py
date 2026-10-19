"""Update saved outlet values without reinterpreting the profile catalog."""

from types import SimpleNamespace
from urllib.parse import urlsplit


def refresh_saved_outlet(record, profile, revision):
    """Preserve saved declarations and capabilities on legacy management edits."""
    from nexent.core.agents.agent_model import ModelConfig
    from nexent.core.model_service.compatibility.legacy_config import (
        legacy_extra_body,
        legacy_thinking_enabled,
    )
    from nexent.core.model_service.registry import model_service_references
    from services.model_runtime_options_service import compile_model_runtime_profile

    extra = record.get("extra_params") or {}
    model = ModelConfig(
        cite_name=record["display_name"], model_name=profile.identity.request_model_id, url=record["base_url"],
        resolved_profile=profile, temperature=record.get("temperature"), top_p=record.get("top_p"),
        max_tokens=record.get("max_tokens"), max_output_tokens=record.get("max_output_tokens"),
        context_window_tokens=record.get("context_window_tokens"),
        default_output_reserve_tokens=record.get("default_output_reserve_tokens"),
        enable_thinking=legacy_thinking_enabled(extra), reasoning_effort=extra.get("reasoning_effort"),
        reasoning_budget_tokens=extra.get("reasoning_budget_tokens"), extra_body=legacy_extra_body(extra),
    )
    updated = compile_model_runtime_profile(model, SimpleNamespace(context_budget_snapshot=None,
                                                                   requested_output_tokens=None))
    data = updated.model_dump()
    data["config_revision"] = revision
    data["identity"]["display_name"] = record["display_name"]
    endpoint = urlsplit(record["base_url"])
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.fragment):
        raise ValueError("MODEL_OUTLET_ENDPOINT_INVALID")
    _ = endpoint.port
    kind = "model_record" if record.get("api_key") else "none"
    data["connection"].update(
        base_url=record["base_url"], ssl_verify=record.get("ssl_verify") if record.get("ssl_verify") is not None else True,
        timeout_seconds=record.get("timeout_seconds") or 60, concurrency_limit=record.get("concurrency_limit"),
        credential_ref={"kind": kind, "model_id": profile.outlet_id},
    )
    data["connection_rules"]["credential_kind"] = kind
    data["bindings"]["auth"] = next(ref.model_dump() for ref in model_service_references()["auth"]
        if ref.ref == ("bearer_token_v1" if kind == "model_record" else "no_auth_v1"))
    source_context = profile.provenance.provider_metadata.get("legacy_context_columns")

    def changed(column):
        if isinstance(source_context, dict) and column in source_context:
            return record.get(column) != source_context[column]
        return record.get(column) is not None

    for field, column in (("combined_window", "context_window_tokens"), ("input_limit", "max_input_tokens"),
                          ("output_limit", "max_output_tokens")):
        if changed(column):
            data["capabilities"]["context"][field] = record.get(column)
    for field, column in (("output_reserve_tokens", "default_output_reserve_tokens"),
                          ("tokenizer_family", "tokenizer_family"), ("capacity_source", "capacity_source"),
                          ("capability_profile_version", "capability_profile_version")):
        if changed(column):
            data["context_configuration"][field] = record.get(column)
    return type(profile).model_validate(data)
