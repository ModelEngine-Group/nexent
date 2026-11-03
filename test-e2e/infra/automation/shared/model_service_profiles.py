# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Controlled profiles composed through the production catalog and registries."""

from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import construct_resolved_model_profile
from nexent.core.model_service.profiles.resolved_profile import ConnectionRules, ContextConfiguration, OutletConnection
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references


def resolved_profile_for_test(base_url, model_id="qwen3.5-plus"):
    catalog = load_profile_catalog()
    refs = model_service_references()
    policy = compose_provider_model_policy(
        catalog, provider_key="alibaba-cn", request_model_id=model_id, model_profile_key=None,
        base_bindings={key: refs[key][0].model_dump() for key in
                       ("protocol", "auth", "adapter", "code_converter", "native_converter")},
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=refs, submitted_values={"enable_thinking": False},
    )
    return construct_resolved_model_profile(
        policy, catalog, tenant_id="controlled-tenant", display_name="controlled-outlet",
        model_type="llm", provider_id="alibaba",
        connection=OutletConnection(base_url=base_url, ssl_verify=True, timeout_seconds=5,
                                    concurrency_limit=None, credential_ref={"kind": "model_record", "model_id": None}),
        connection_rules=ConnectionRules(credential_kind="model_record", relative_path="/chat/completions",
                                         method="POST", headers={}),
        context_configuration=ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                                                   capacity_source="profile", capability_profile_version=None),
        registered_references=refs,
    )
