"""Trusted in-process plugin registry for agent runtime extensions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .models import OperatorSpec
from .tool_factory import ToolFactory


class PluginError(ValueError):
    """Base error for plugin registry failures."""


class DuplicatePluginRegistrationError(PluginError):
    """Raised when a plugin contribution is registered twice."""


class PluginConfigValidationError(PluginError):
    """Raised when plugin config fails validation."""


class UntrustedPluginRegistrationError(PluginError):
    """Raised when code tries to register an untrusted plugin."""


PluginRegistrar = Callable[["PluginRegistry", Mapping[str, Any]], None]
PluginConfigSchema = Mapping[str, Any] | Callable[[Mapping[str, Any]], bool | None]


@dataclass
class ToolFactoryRegistration:
    """Declarative plugin tool factory registration."""

    source: str
    factory: ToolFactory
    class_name: str | None = None


@dataclass
class OperatorFactoryRegistration:
    """Declarative plugin operator factory registration."""

    name: str
    factory: Callable[[OperatorSpec], Any]


@dataclass
class PluginRegistry:
    """Registry for built-in trusted plugin contributions."""

    _providers: dict[str, Any] = field(default_factory=dict)
    _tool_factories: dict[tuple[str, str | None], ToolFactoryRegistration] = (
        field(default_factory=dict)
    )
    _operators: dict[str, OperatorFactoryRegistration] = field(default_factory=dict)
    _runtimes: dict[str, Any] = field(default_factory=dict)
    _plugins: set[str] = field(default_factory=set)

    def register_plugin(
        self,
        name: str,
        registrar: PluginRegistrar,
        *,
        config: Mapping[str, Any] | None = None,
        config_schema: PluginConfigSchema | None = None,
        trusted: bool = True,
    ) -> None:
        """Register a trusted in-process plugin and execute its registrar."""
        plugin_name = _normalize_name(name, "plugin name")
        if not trusted:
            raise UntrustedPluginRegistrationError(
                f"Plugin '{plugin_name}' is not trusted for v1 registration."
            )
        if plugin_name in self._plugins:
            raise DuplicatePluginRegistrationError(
                f"Duplicate plugin registration: {plugin_name}."
            )
        plugin_config = dict(config or {})
        validate_plugin_config(plugin_config, config_schema, plugin_name=plugin_name)
        registrar(self, plugin_config)
        self._plugins.add(plugin_name)

    def register_provider(self, provider: Any) -> None:
        """Register a capability provider contributed by a plugin."""
        provider_name = _normalize_name(getattr(provider, "name", ""), "provider name")
        if provider_name in self._providers:
            raise DuplicatePluginRegistrationError(
                f"Duplicate plugin provider: {provider_name}."
            )
        self._providers[provider_name] = provider

    def register_tool_factory(
        self,
        source: str,
        factory: ToolFactory,
        *,
        class_name: str | None = None,
    ) -> None:
        """Register a tool factory contributed by a plugin."""
        key = (
            _normalize_name(source, "tool factory source"),
            _normalize_optional_name(class_name),
        )
        if key in self._tool_factories:
            raise DuplicatePluginRegistrationError(
                f"Duplicate plugin tool factory: {key[0]}:{key[1] or '*'}."
            )
        self._tool_factories[key] = ToolFactoryRegistration(
            source=key[0],
            factory=factory,
            class_name=key[1],
        )

    def register_operator(
        self,
        name: str,
        factory: Callable[[OperatorSpec], Any],
    ) -> None:
        """Register an operator factory contributed by a plugin."""
        operator_name = _normalize_name(name, "operator name")
        if operator_name in self._operators:
            raise DuplicatePluginRegistrationError(
                f"Duplicate plugin operator: {operator_name}."
            )
        self._operators[operator_name] = OperatorFactoryRegistration(
            name=operator_name,
            factory=factory,
        )

    def register_runtime(self, runtime: Any) -> None:
        """Register a runtime adapter contributed by a plugin."""
        runtime_name = _normalize_name(getattr(runtime, "name", ""), "runtime name")
        if runtime_name in self._runtimes:
            raise DuplicatePluginRegistrationError(
                f"Duplicate plugin runtime: {runtime_name}."
            )
        self._runtimes[runtime_name] = runtime

    def list_providers(self) -> list[Any]:
        """Return plugin providers in deterministic registration-name order."""
        return [self._providers[name] for name in sorted(self._providers)]

    def list_tool_factories(self) -> list[ToolFactoryRegistration]:
        """Return plugin tool factory registrations."""
        return [
            self._tool_factories[key]
            for key in sorted(self._tool_factories, key=lambda item: (item[0], item[1] or ""))
        ]

    def list_operators(self) -> list[OperatorFactoryRegistration]:
        """Return plugin operator registrations."""
        return [self._operators[name] for name in sorted(self._operators)]

    def list_runtimes(self) -> list[Any]:
        """Return plugin runtime adapters."""
        return [self._runtimes[name] for name in sorted(self._runtimes)]


def validate_plugin_config(
    config: Mapping[str, Any],
    schema: PluginConfigSchema | None,
    *,
    plugin_name: str,
) -> None:
    """Validate a plugin config using a callable or minimal object schema."""
    if schema is None:
        return
    if callable(schema):
        try:
            result = schema(config)
        except Exception as exc:
            raise PluginConfigValidationError(
                f"Plugin '{plugin_name}' config validation failed: {exc}"
            ) from exc
        if result is False:
            raise PluginConfigValidationError(
                f"Plugin '{plugin_name}' config validation failed."
            )
        return
    _validate_mapping_schema(config, schema, plugin_name=plugin_name)


def _validate_mapping_schema(
    config: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    plugin_name: str,
) -> None:
    schema_type = schema.get("type")
    if schema_type not in {None, "object"}:
        raise PluginConfigValidationError(
            f"Plugin '{plugin_name}' config schema type must be object."
        )
    required = schema.get("required") or []
    for key in required:
        if key not in config:
            raise PluginConfigValidationError(
                f"Plugin '{plugin_name}' config missing required key: {key}."
            )
    properties = schema.get("properties") or {}
    if not isinstance(properties, Mapping):
        raise PluginConfigValidationError(
            f"Plugin '{plugin_name}' config schema properties must be an object."
        )
    for key, property_schema in properties.items():
        if key in config:
            _validate_property_type(
                config[key],
                property_schema,
                plugin_name=plugin_name,
                key=str(key),
            )


def _validate_property_type(
    value: Any,
    property_schema: Any,
    *,
    plugin_name: str,
    key: str,
) -> None:
    if not isinstance(property_schema, Mapping):
        return
    expected_type = property_schema.get("type")
    if expected_type is None:
        return
    if expected_type == "array":
        valid = isinstance(value, list)
    elif expected_type == "boolean":
        valid = isinstance(value, bool)
    elif expected_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected_type == "number":
        valid = isinstance(value, int | float) and not isinstance(value, bool)
    elif expected_type == "object":
        valid = isinstance(value, Mapping)
    elif expected_type == "string":
        valid = isinstance(value, str)
    else:
        raise PluginConfigValidationError(
            f"Plugin '{plugin_name}' config key '{key}' has unsupported schema type: "
            f"{expected_type}."
        )
    if not valid:
        raise PluginConfigValidationError(
            f"Plugin '{plugin_name}' config key '{key}' must be {expected_type}."
        )


def _normalize_name(value: str, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise PluginError(f"Plugin {label} cannot be empty.")
    return normalized


def _normalize_optional_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
