# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Selected model-visible resources shared by Agent runtime implementations."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from nexent.core.model_service.contracts import ModelMessage, ToolDefinition
from nexent.core.model_service.profiles.contracts import NonBlankString, ProfileContract


class ResourceItem(ProfileContract):
    message: ModelMessage
    source: NonBlankString
    order: Annotated[int, Field(ge=0)]


class RuntimeResourceView(ProfileContract):
    """Only selected model-visible data; no executable bindings or arbitrary metadata."""

    instructions: list[ResourceItem] = Field(default_factory=list)
    references: list[ResourceItem] = Field(default_factory=list)
    history: list[ResourceItem] = Field(default_factory=list)
    current_user_input: ResourceItem
    tool_observations: list[ResourceItem] = Field(default_factory=list)
    tool_definitions: list[ToolDefinition] = Field(default_factory=list)
    authorized_metadata: list[ResourceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resources(self) -> Self:
        items = self.items()
        if len({item.order for item in items}) != len(items):
            raise ValueError("Resource ordering must be unique")
        if len({item.message.message_id for item in items}) != len(items):
            raise ValueError("Resource message identities must be unique")
        if len({tool.name for tool in self.tool_definitions}) != len(self.tool_definitions):
            raise ValueError("Authorized tool names must be unique")
        for item in items:
            message = item.message
            if message.tool_calls and message.semantic_role not in {"assistant_history", "assistant"}:
                raise ValueError("Tool calls require an assistant history item")
            if message.tool_call_id is not None and message.semantic_role not in {"tool_result", "tool"}:
                raise ValueError("Tool result association requires an observation")
        for group, roles in (
            (self.instructions, {"platform_instruction", "application_instruction"}),
            (self.references + self.authorized_metadata, {"reference_data"}),
            (self.history, {"user_input", "assistant_history", "tool_result", "user", "assistant", "tool"}),
            (self.tool_observations, {"tool_result", "tool"}),
            ([self.current_user_input], {"user_input"}),
        ):
            if any(item.message.semantic_role not in roles for item in group):
                raise ValueError("Resource role does not match its authorized group")
        return self

    def items(self):
        return (self.instructions + self.references + self.history + self.tool_observations
                + self.authorized_metadata + [self.current_user_input])
