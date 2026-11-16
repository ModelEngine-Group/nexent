# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Versioned transformations change the wire value without changing saved outlet data."""

import pytest
from nexent.core.model_service.adapters.openai_chat import ModelAdapterError, OpenAIChatAdapter
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.parameter_transforms import parameter_transform_references, transform_parameter
from nexent.core.model_service.profiles.outlet_storage import decode_resolved_model_profile, encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references


def binding(ref="thinking_toggle_v1", version=1):
    return {"path": "/thinking/type", "transform_ref": ref, "transform_version": version}










@pytest.mark.parametrize("value,expected", [(True, "enabled"), (False, "disabled")])
def test_saved_rule_executes_same_registered_transform_in_request(openai_profile, value, expected):
    data = openai_profile.model_dump()
    refs = model_service_references()
    for key in ("auth", "code_converter", "native_converter"):
        data["bindings"][key] = refs[key][0].model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 12
    data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] != "enable_thinking"]
    data["parameter_rules"].append({
        "key": "enable_thinking", "schema": {"type": "boolean"},
        "visible": True, "editable": True, "required": False,
        "allowed_scopes": ["outlet", "conversation"], "ui_group": "reasoning",
        "owner": "provider", "source": {"ref": "controlled_mapping", "version": 1},
        "api_binding": binding(),
    })
    data["parameter_values"]["enable_thinking"] = value
    profile = openai_profile.__class__.model_validate(data)
    row = encode_resolved_model_profile(profile, registered_references=refs)
    restored = decode_resolved_model_profile(row, registered_references=refs)
    request = ModelRequest(request_id="test", outlet_id=12, config_revision=restored.config_revision,
        messages=[ModelMessage(semantic_role="user_input", content_parts=[{"type": "text", "text": "Hello"}])])
    prepared = OpenAIChatAdapter().prepare_http_request(request, restored)
    assert prepared.json_body["thinking"]["type"] == expected
    assert restored.parameter_values["enable_thinking"] is value
    assert restored == profile


def test_adapter_rejects_unavailable_transform_before_http(openai_profile):
    data = openai_profile.model_dump()
    data["parameter_rules"][0]["api_binding"]["transform_version"] = 2
    profile = openai_profile.__class__.model_validate(data)
    request = ModelRequest(request_id="test", outlet_id=profile.outlet_id, config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user_input", content_parts=[{"type": "text", "text": "Hello"}])])
    with pytest.raises(ModelAdapterError):
        OpenAIChatAdapter().prepare_http_request(request, profile)


def test_registry_exports_the_same_versioned_transforms():
    assert model_service_references()["parameter_transform"] == parameter_transform_references()
