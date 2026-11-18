# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Synthetic standard model rows shared by focused model-storage regressions."""

from configs.model_catalog_loader import resolve_reasoning_capability
from management.services.model.outlet_migration import build_legacy_outlet_snapshot
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references


def legacy_record(**changes):
    record = {"model_id": 7, "tenant_id": "tenant", "model_type": "llm", "model_repo": "",
        "model_name": "qwen3.5-plus", "model_factory": "alibaba-cn", "display_name": "outlet",
        "base_url": "http://127.0.0.1:9999/v1", "api_key": "unit-secret", "max_output_tokens": 512,
        "default_output_reserve_tokens": 256, "temperature": .7, "top_p": None,
        "extra_params": {"enable_thinking": False}}
    return {**record, **changes}


def canonical_record(record):
    profile = build_legacy_outlet_snapshot(record,
        legacy_capability=resolve_reasoning_capability(record["model_name"], record["base_url"], record["model_factory"]),
        migrated_at="2026-11-16T00:00:00Z")
    from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules

    profile = ensure_outlet_parameter_rules(profile)
    return {**record, **encode_resolved_model_profile(profile, registered_references=model_service_references())}


def stub_resolved_model_catalog(mocker, *rows):
    from management.services.agent.preparation import model_bindings
    from runtime.agentos import prepared_evaluation

    catalog = {(row["model_id"], row["tenant_id"]): row for row in rows}
    mocker.patch.object(
        model_bindings,
        "get_model_by_model_id",
        side_effect=lambda model_id, tenant_id: catalog.get((model_id, tenant_id)),
    )
    mocker.patch.object(model_bindings, "read_agent_model_overrides", return_value={})
    mocker.patch.object(prepared_evaluation, "read_agent_model_overrides", return_value={})
