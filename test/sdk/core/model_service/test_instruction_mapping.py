# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Traditional instruction declarations and registry boundaries."""

import pytest
from nexent.core.model_service.profiles.contracts import (
    InstructionMappingDefinition,
    VersionedReference,
)
from nexent.core.model_service.profiles.instruction_mapping import (
    InstructionMappingError,
    resolve_instruction_mapping,
    validate_instruction_mapping,
)
from pydantic import ValidationError


def traditional():
    return resolve_instruction_mapping(
        VersionedReference(ref="system_only_v1", version=1)
    )


def test_traditional_strategy_maps_every_semantic_resource_explicitly():
    profile = traditional()
    assert profile.instruction_hierarchy == ["system", "user"]
    assert profile.supported_roles == ["system", "user", "assistant", "tool"]
    assert profile.mappings.model_dump() == {
        "platform_instruction": "system",
        "application_instruction": "system",
        "user_input": "user",
        "assistant_history": "assistant",
        "tool_result": "tool",
        "reference_data": "user",
    }
    assert profile.ordering == [
        "platform_instruction",
        "agent_instruction",
        "activated_skill_instruction",
    ]
    assert profile.reference_placement == "user_data_block"
    assert validate_instruction_mapping(profile) == VersionedReference(
        ref="system_only_v1", version=1
    )


@pytest.mark.parametrize(
    "ref,version", [("system_only_v1", 2), ("developer_v1", 1), ("package.module", 1)]
)
def test_unknown_strategy_or_version_never_imports_or_falls_back(ref, version):
    with pytest.raises(
        InstructionMappingError, match="UNSUPPORTED_INSTRUCTION_MAPPING"
    ):
        resolve_instruction_mapping(VersionedReference(ref=ref, version=version))


@pytest.mark.parametrize(
    "field,value",
    [
        ("supported_roles", ["system", "user", "assistant"]),
        ("supported_roles", ["system", "user", "assistant", "tool", "tool"]),
        ("instruction_hierarchy", []),
        ("instruction_hierarchy", ["developer", "user"]),
        ("ordering", []),
        ("strategy_version", True),
        ("strategy_version", 0),
        ("unknown", 1),
    ],
)
def test_contract_rejects_undefined_or_missing_role_semantics(field, value):
    data = traditional().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        InstructionMappingDefinition.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("instruction_hierarchy", ["user", "system"]),
        ("supported_roles", ["system", "user", "assistant", "tool", "developer"]),
        ("reference_placement", "tool"),
        ("ordering", ["agent_instruction", "platform_instruction"]),
    ],
)
def test_structurally_valid_unregistered_behavior_is_not_accepted(field, value):
    data = traditional().model_dump()
    data[field] = value
    with pytest.raises(
        InstructionMappingError, match="UNSUPPORTED_INSTRUCTION_MAPPING"
    ):
        validate_instruction_mapping(InstructionMappingDefinition.model_validate(data))


def test_semantic_role_changes_require_a_registered_strategy():
    data = traditional().model_dump()
    data["mappings"]["platform_instruction"] = "user"
    with pytest.raises(InstructionMappingError):
        validate_instruction_mapping(InstructionMappingDefinition.model_validate(data))
    del data["mappings"]["tool_result"]
    with pytest.raises(ValidationError):
        InstructionMappingDefinition.model_validate(data)


def test_returned_declarations_do_not_mutate_registry_defaults():
    profile = traditional()
    profile.supported_roles.append("developer")
    profile.ordering.reverse()
    assert traditional().supported_roles == ["system", "user", "assistant", "tool"]
    assert traditional().ordering[0] == "platform_instruction"
    with pytest.raises(ValidationError):
        profile.strategy_id = "developer"
