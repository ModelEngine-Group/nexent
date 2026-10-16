# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared controlled outlet fixture for provider adapter unit boundaries."""

import pytest


@pytest.fixture(scope="module")
def openai_profile():
    # Keep unrelated contract tests collectible before adapter-specific fixtures are used.
    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
    from nexent.core.model_service.profiles.composition import compose_provider_model_policy
    from nexent.core.model_service.profiles.contracts import VersionedReference
    from nexent.core.model_service.profiles.outlet_resolution import (
        construct_resolved_model_profile,
    )
    from nexent.core.model_service.profiles.resolved_profile import (
        ConnectionRules,
        ContextConfiguration,
        OutletConnection,
    )
    from nexent.core.model_service.profiles.resolver import load_profile_catalog

    catalog = load_profile_catalog()
    ref = VersionedReference(ref="adapter_fixture_v1", version=1)
    registry = {
        key: [ref]
        for key in ("protocol", "auth", "adapter", "code_converter", "native_converter")
    }
    registry["protocol"] = [OpenAIChatAdapter.protocol_reference]
    registry["adapter"] = [OpenAIChatAdapter.reference]
    registry["parameter_transform"] = [VersionedReference(ref="identity_v1", version=1)]
    policy = compose_provider_model_policy(
        catalog,
        provider_key="alibaba-cn",
        request_model_id="qwen3.5-plus",
        model_profile_key=None,
        base_bindings={
            key: references[0].model_dump()
            for key, references in registry.items()
            if key != "parameter_transform"
        },
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=registry,
        submitted_values={"enable_thinking": False},
    )
    return construct_resolved_model_profile(
        policy,
        catalog,
        tenant_id="tenant",
        display_name="outlet",
        model_type="llm",
        provider_id="alibaba",
        connection=OutletConnection(
            base_url="https://example.test/v1",
            ssl_verify=True,
            timeout_seconds=10,
            concurrency_limit=None,
            credential_ref={"kind": "model_record", "model_id": None},
        ),
        connection_rules=ConnectionRules(
            credential_kind="model_record",
            relative_path="/chat/completions",
            method="POST",
            headers={},
        ),
        context_configuration=ContextConfiguration(
            output_reserve_tokens=None,
            tokenizer_family=None,
            capacity_source="profile",
            capability_profile_version=None,
        ),
        registered_references=registry,
    )
