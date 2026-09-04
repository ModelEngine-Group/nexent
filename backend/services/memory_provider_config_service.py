"""Configuration management service for external memory providers.

Handles CRUD operations on provider configurations with EAV parameter
validation against plugin config_schema definitions, and secret masking
for API responses.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from database import memory_provider_config_db, memory_provider_config_param_db
from services.memory_provider_plugin_loader import PluginLoader

logger = logging.getLogger("memory_provider_config_service")


class MemoryProviderConfigService:
    """Manage external memory provider configurations.

    Validates EAV parameters against the plugin's config_schema, persists
    configurations to the database, and masks secret fields in API responses.
    """

    def __init__(self, plugin_loader: PluginLoader):
        self._plugin_loader = plugin_loader

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_provider(
        self,
        tenant_id: str,
        provider_name: str,
        connection_type: str,
        params: Dict[str, str],
        enabled: bool = False,
        timeout_seconds: int = 30,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new provider configuration with validated parameters.

        Args:
            tenant_id: Owning tenant identifier.
            provider_name: Human-readable provider name (unique per tenant).
            connection_type: Must be ``"plugin"`` in Phase 3.
            params: EAV parameters including ``plugin.name``.
            enabled: Whether the provider is active immediately.
            timeout_seconds: Request timeout for provider calls.
            created_by: User who created this configuration.

        Returns:
            Provider config dict with masked parameters.

        Raises:
            ValueError: On validation failure (bad connection_type, missing
                plugin.name, unknown plugin, missing required fields).
        """
        if connection_type != "plugin":
            raise ValueError(
                f"Unsupported connection_type {connection_type!r}. "
                "Phase 3 only supports 'plugin'."
            )

        plugin_name = params.get("plugin.name")
        if not plugin_name:
            raise ValueError("params must contain 'plugin.name'")

        plugin_info = self._plugin_loader.get_plugin(plugin_name)
        if plugin_info is None:
            available = [p.name for p in self._plugin_loader.list_plugins()]
            raise ValueError(
                f"Plugin {plugin_name!r} is not installed. "
                f"Available plugins: {available}"
            )

        self._validate_params(params, plugin_name)

        config_id = memory_provider_config_db.insert_provider_config({
            "tenant_id": tenant_id,
            "provider_name": provider_name,
            "connection_type": connection_type,
            "enabled": enabled,
            "timeout_seconds": timeout_seconds,
            "created_by": created_by,
            "updated_by": created_by,
        })
        if config_id is None:
            raise ValueError(
                "Failed to insert provider config. "
                "A provider with this name may already exist for this tenant."
            )

        ok = memory_provider_config_param_db.upsert_params(config_id, params)
        if not ok:
            logger.error(
                "Failed to insert params for provider_config_id=%d, "
                "rolling back config row",
                config_id,
            )
            memory_provider_config_db.soft_delete_provider_config(
                config_id, created_by or "system"
            )
            raise ValueError("Failed to insert provider parameters")

        return self._build_response(config_id, params, plugin_info.config_schema)

    def get_provider(self, provider_config_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single provider configuration with masked parameters.

        Args:
            provider_config_id: Primary key of the provider config.

        Returns:
            Provider config dict with masked params, or ``None`` if not found.
        """
        config = memory_provider_config_db.get_provider_config(provider_config_id)
        if config is None:
            return None

        params = memory_provider_config_param_db.get_params(provider_config_id)
        config_schema = self._get_config_schema(params)

        return self._build_response(provider_config_id, params, config_schema, base=config)

    def list_providers(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List all provider configurations for a tenant with masked parameters.

        Args:
            tenant_id: Tenant to list providers for.

        Returns:
            List of provider config dicts with masked params.
        """
        configs = memory_provider_config_db.list_provider_configs(tenant_id)
        results = []
        for config in configs:
            pid = config["provider_config_id"]
            params = memory_provider_config_param_db.get_params(pid)
            config_schema = self._get_config_schema(params)
            results.append(
                self._build_response(pid, params, config_schema, base=config)
            )
        return results

    def update_provider(
        self,
        provider_config_id: int,
        data: Dict[str, Any],
        updated_by: str,
    ) -> Optional[Dict[str, Any]]:
        """Update a provider configuration.

        Main-table fields (``provider_name``, ``enabled``, ``timeout_seconds``)
        are updated if present in *data*. If ``params`` is provided, they are
        validated against the plugin config_schema and fully replaced.

        Args:
            provider_config_id: Primary key of the provider config.
            data: Fields to update. May include ``params`` dict.
            updated_by: User performing the update.

        Returns:
            Updated provider config dict with masked params, or ``None``
            if the config was not found.

        Raises:
            ValueError: On parameter validation failure.
        """
        config = memory_provider_config_db.get_provider_config(provider_config_id)
        if config is None:
            return None

        main_fields: Dict[str, Any] = {"updated_by": updated_by}
        for key in ("provider_name", "enabled", "timeout_seconds"):
            if key in data:
                main_fields[key] = data[key]

        ok = memory_provider_config_db.update_provider_config(
            provider_config_id, main_fields
        )
        if not ok:
            logger.error(
                "Failed to update provider config id=%d", provider_config_id
            )
            return None

        params = memory_provider_config_param_db.get_params(provider_config_id)
        if "params" in data:
            new_params = data["params"]

            plugin_name = new_params.get("plugin.name") or params.get("plugin.name")
            if plugin_name:
                self._validate_params(new_params, plugin_name)

            ok = memory_provider_config_param_db.upsert_params(
                provider_config_id, new_params
            )
            if not ok:
                logger.error(
                    "Failed to upsert params for provider_config_id=%d",
                    provider_config_id,
                )
                return None
            params = new_params

        config_schema = self._get_config_schema(params)

        config = memory_provider_config_db.get_provider_config(provider_config_id)
        return self._build_response(
            provider_config_id, params, config_schema, base=config
        )

    def delete_provider(
        self, provider_config_id: int, updated_by: str
    ) -> bool:
        """Soft-delete a provider configuration and its parameters.

        Args:
            provider_config_id: Primary key of the provider config.
            updated_by: User performing the deletion.

        Returns:
            ``True`` if deletion succeeded, ``False`` otherwise.
        """
        ok = memory_provider_config_db.soft_delete_provider_config(
            provider_config_id, updated_by
        )
        if not ok:
            logger.error(
                "Failed to soft-delete provider config id=%d",
                provider_config_id,
            )
            return False

        param_ok = memory_provider_config_param_db.delete_params(
            provider_config_id
        )
        if not param_ok:
            logger.warning(
                "Provider config id=%d was deleted but param cleanup failed",
                provider_config_id,
            )

        return True

    def get_enabled_providers(
        self, tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Return all enabled providers for a tenant with plain (unmasked) params.

        This method is intended for internal use by the transparent proxy
        and ingest pipeline where actual credentials are needed.

        Args:
            tenant_id: Tenant to query.

        Returns:
            List of provider config dicts with unmasked params.
        """
        configs = memory_provider_config_db.list_provider_configs(
            tenant_id, enabled_only=True
        )
        results = []
        for config in configs:
            pid = config["provider_config_id"]
            params = memory_provider_config_param_db.get_params(pid)
            result = {**config, "params": params}
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_config_schema(self, params: Dict[str, str]) -> List[Dict[str, Any]]:
        """Resolve the config_schema for the plugin referenced by params."""
        plugin_name = params.get("plugin.name")
        if not plugin_name:
            return []
        plugin_info = self._plugin_loader.get_plugin(plugin_name)
        if plugin_info is None:
            return []
        return plugin_info.config_schema

    def _build_response(
        self,
        provider_config_id: int,
        params: Dict[str, str],
        config_schema: List[Dict[str, Any]],
        base: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Assemble a provider config response dict with masked params."""
        if base is None:
            base = memory_provider_config_db.get_provider_config(
                provider_config_id
            ) or {}
        result = {**base, "params": self._mask_params(params, config_schema)}
        return result

    @staticmethod
    def _mask_params(
        params: Dict[str, str], config_schema: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Mask secret parameter values for safe display.

        Masking rules (from Functional Design §5.4):
        - Length <= 8: show ``***``
        - Length > 8: show first 3 chars + ``***`` + last 4 chars

        A parameter is considered secret when:
        - Its key ends with ``api_key``, OR
        - Its config_schema entry has ``type: "secret"``
        """
        secret_keys: set[str] = set()
        for field in config_schema:
            if field.get("type") == "secret":
                secret_keys.add(f"plugin.{field['key']}")
                secret_keys.add(field["key"])

        masked: Dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                masked[key] = value
                continue

            is_secret = (
                key.endswith("api_key")
                or key in secret_keys
            )
            if is_secret:
                masked[key] = _mask_value(value)
            else:
                masked[key] = value

        return masked

    def _validate_params(
        self, params: Dict[str, str], plugin_name: str
    ) -> None:
        """Validate EAV parameters against the plugin's config_schema.

        Args:
            params: The EAV parameters to validate.
            plugin_name: Name of the plugin to validate against.

        Raises:
            ValueError: If validation fails.
        """
        plugin_info = self._plugin_loader.get_plugin(plugin_name)
        if plugin_info is None:
            raise ValueError(f"Plugin {plugin_name!r} is not installed")

        config_schema = plugin_info.config_schema
        if not config_schema:
            return

        for field in config_schema:
            if not field.get("required", False):
                continue

            field_key = field["key"]
            prefixed_key = f"plugin.{field_key}"
            value = params.get(prefixed_key) or params.get(field_key)

            if value is None or value == "":
                raise ValueError(
                    f"Required parameter {field_key!r} is missing "
                    f"for plugin {plugin_name!r}"
                )


def _mask_value(value: str) -> str:
    """Apply masking to a single secret value.

    Rules:
    - Length <= 8: ``***``
    - Length > 8: first 3 + ``***`` + last 4
    """
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"
