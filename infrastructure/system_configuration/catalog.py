# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Frozen catalog and immutable snapshots for managed system settings."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

ConfigValue = int | float | bool | tuple[str, ...]
ConfigInput = ConfigValue | list[str]
ConfigKind = Literal["integer", "number", "boolean", "resource_refs"]
NL2AGENT_RESOURCE_DENYLIST = "NL2AGENT_RESOURCE_DENYLIST"
MAX_RESOURCE_REFS = 200
_RESOURCE_REF = re.compile(
    r"(?:(?:tool|skill|tenant_skill_repository|tenant_mcp_repository):[1-9][0-9]*"
    r"|nexent_official_skill:(?:[A-Za-z0-9_.~-]|%[0-9A-F]{2})+)"
)


class ConfigurationValidationError(ValueError):
    """Reject unknown, missing or invalid managed configuration values."""


@dataclass(frozen=True)
class ConfigurationDefinition:
    key: str
    kind: ConfigKind
    group: str
    default: ConfigValue
    effect_key: str
    unit_key: str | None = None
    recommendation_rule: str | None = None

    @property
    def label_key(self) -> str:
        return f"systemConfig.param.{self.key}.label"

    @property
    def description_key(self) -> str:
        return f"systemConfig.param.{self.key}.desc"


@dataclass(frozen=True)
class SystemConfigurationSnapshot:
    values: Mapping[str, ConfigValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def get(self, key: str) -> ConfigValue:
        return self.values[key]

    def to_dict(self) -> dict[str, ConfigValue]:
        return dict(self.values)


def _integer(
    key: str, group: str, default: int, effect_key: str, unit_key: str
) -> ConfigurationDefinition:
    return ConfigurationDefinition(key, "integer", group, default, effect_key, unit_key)


def _number(key: str, default: float, effect_key: str) -> ConfigurationDefinition:
    return ConfigurationDefinition(
        key, "number", "runtime", default, effect_key, "systemConfig.unit.second"
    )


class SystemConfigurationCatalog:
    def __init__(self, definitions: tuple[ConfigurationDefinition, ...]) -> None:
        self.definitions = definitions
        self._by_key = {item.key: item for item in definitions}
        self.defaults = MappingProxyType(
            {item.key: item.default for item in definitions}
        )

    def definition(self, key: str) -> ConfigurationDefinition:
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise ConfigurationValidationError(
                f"Unmanaged configuration key: {key}"
            ) from exc

    def build_snapshot(
        self, values: Mapping[str, ConfigInput]
    ) -> SystemConfigurationSnapshot:
        expected = set(self._by_key)
        actual = set(values)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if missing:
            raise ConfigurationValidationError(
                f"Missing required configuration keys: {', '.join(missing)}"
            )
        if unknown:
            raise ConfigurationValidationError(
                f"Unmanaged configuration keys: {', '.join(unknown)}"
            )
        validated = {
            key: self._validate_value(self._by_key[key], value)
            for key, value in values.items()
        }
        return SystemConfigurationSnapshot(validated)

    def validate_changes(
        self,
        current: Mapping[str, ConfigValue],
        changes: Mapping[str, ConfigInput],
    ) -> SystemConfigurationSnapshot:
        for key in changes:
            self.definition(key)
        return self.build_snapshot({**current, **changes})

    @staticmethod
    def _validate_value(
        definition: ConfigurationDefinition, value: ConfigInput
    ) -> ConfigValue:
        if definition.kind == "resource_refs":
            if (
                type(value) not in (list, tuple)
                or len(value) > MAX_RESOURCE_REFS
                or any(
                    type(ref) is not str or len(ref) > 1024 or not _RESOURCE_REF.fullmatch(ref)
                    for ref in value
                )
                or len(set(value)) != len(value)
            ):
                raise ConfigurationValidationError(
                    f"{definition.key} must contain up to {MAX_RESOURCE_REFS} unique candidate references"
                )
            return tuple(sorted(value))
        if definition.kind == "boolean":
            if type(value) is not bool:
                raise ConfigurationValidationError(
                    f"{definition.key} must be a boolean"
                )
            return value
        if definition.kind == "integer":
            if type(value) is not int or value <= 0:
                raise ConfigurationValidationError(
                    f"{definition.key} must be a positive integer"
                )
            return value
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ConfigurationValidationError(
                f"{definition.key} must be a finite positive number"
            )
        return value


DEFAULT_CATALOG = SystemConfigurationCatalog(
    (
        _integer(
            "MAX_TENANT_COUNT",
            "tenant",
            100,
            "systemConfig.effect.createTenant",
            "systemConfig.unit.tenant",
        ),
        _integer(
            "MAX_USERS_PER_TENANT",
            "tenant",
            10000,
            "systemConfig.effect.createUser",
            "systemConfig.unit.user",
        ),
        _integer(
            "MAX_GROUPS_PER_TENANT",
            "tenant",
            1000,
            "systemConfig.effect.createGroup",
            "systemConfig.unit.group",
        ),
        _integer(
            "MAX_ADMINS_PER_TENANT",
            "tenant",
            1000,
            "systemConfig.effect.roleChange",
            "systemConfig.unit.person",
        ),
        _integer(
            "MAX_KNOWLEDGE_BASES_PER_TENANT",
            "capacity",
            10000,
            "systemConfig.effect.createKnowledge",
            "systemConfig.unit.kb",
        ),
        _integer(
            "MAX_KNOWLEDGE_BASES_PER_USER",
            "capacity",
            10,
            "systemConfig.effect.createKnowledge",
            "systemConfig.unit.kb",
        ),
        _integer(
            "MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER",
            "capacity",
            1000,
            "systemConfig.effect.createKnowledge",
            "systemConfig.unit.kb",
        ),
        _integer(
            "MAX_KNOWLEDGE_FILE_SIZE_MB",
            "upload",
            100,
            "systemConfig.effect.nextUpload",
            "systemConfig.unit.mb",
        ),
        _integer(
            "MAX_CONVERSATION_TURNS",
            "capacity",
            100,
            "systemConfig.effect.nextTurn",
            "systemConfig.unit.turn",
        ),
        _integer(
            "MAX_CONVERSATIONS_PER_USER",
            "capacity",
            1000,
            "systemConfig.effect.createConversation",
            "systemConfig.unit.conversation",
        ),
        _integer(
            "MAX_MCP_SERVICES_PER_TENANT",
            "capacity",
            1000,
            "systemConfig.effect.createMcp",
            "systemConfig.unit.service",
        ),
        _number(
            "MCP_REQUEST_TIMEOUT_SECONDS", 10, "systemConfig.effect.nextMcpConnect"
        ),
        _integer(
            "MAX_EVALUATION_SET_FILE_SIZE_MB",
            "upload",
            20,
            "systemConfig.effect.nextUpload",
            "systemConfig.unit.mb",
        ),
        _number(
            "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS", 60, "systemConfig.effect.nextToolCall"
        ),
        _number(
            "RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS",
            120,
            "systemConfig.effect.nextRun",
        ),
        ConfigurationDefinition(
            "LLM_INCLUDE_LOGPROBS",
            "boolean",
            "runtime",
            False,
            "systemConfig.effect.nextModelBinding",
        ),
        _integer(
            "MAX_SKILLS_PER_TENANT",
            "capacity",
            1000,
            "systemConfig.effect.createSkill",
            "systemConfig.unit.skill",
        ),
        _integer(
            "MAX_SKILL_UPLOAD_SIZE_MB",
            "upload",
            10,
            "systemConfig.effect.nextUpload",
            "systemConfig.unit.mb",
        ),
        ConfigurationDefinition(
            NL2AGENT_RESOURCE_DENYLIST,
            "resource_refs",
            "runtime",
            (),
            "systemConfig.effect.nextResourceRecommendation",
        ),
    )
)
