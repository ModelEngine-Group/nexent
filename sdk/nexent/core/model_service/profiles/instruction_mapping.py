# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Registered traditional instruction metadata, independent of prompt rendering."""

from nexent.core.model_service.profiles.contracts import InstructionMappingDefinition, VersionedReference


class InstructionMappingError(ValueError):
    """A sanitized registry error without caller-supplied prompt content."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def resolve_instruction_mapping(reference: VersionedReference) -> InstructionMappingDefinition:
    """Return a detached declaration for the initial traditional role strategy."""
    if reference.ref != "system_only_v1" or reference.version != 1:
        raise InstructionMappingError("UNSUPPORTED_INSTRUCTION_MAPPING")
    return InstructionMappingDefinition(
        strategy_id="system_only",
        strategy_version=1,
        instruction_hierarchy=["system", "user"],
        supported_roles=["system", "user", "assistant", "tool"],
        mappings={
            "platform_instruction": "system",
            "application_instruction": "system",
            "user_input": "user",
            "assistant_history": "assistant",
            "tool_result": "tool",
            "reference_data": "user",
        },
        ordering=["platform_instruction", "agent_instruction", "activated_skill_instruction"],
        reference_placement="user_data_block",
    )


def validate_instruction_mapping(definition: InstructionMappingDefinition) -> VersionedReference:
    """Reject declarations that claim unimplemented authority or mapping behavior."""
    reference = VersionedReference(
        ref=f"{definition.strategy_id}_v{definition.strategy_version}", version=definition.strategy_version
    )
    registered = resolve_instruction_mapping(reference)
    if definition.model_dump() != registered.model_dump():
        raise InstructionMappingError("UNSUPPORTED_INSTRUCTION_MAPPING")
    return reference
