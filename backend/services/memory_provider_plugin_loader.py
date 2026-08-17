"""Plugin loader for external memory providers.

Scans a configured directory for memory provider plugins, validates their
plugin.yaml manifests and protocol conformance, and provides factory methods
to instantiate provider classes at runtime.
"""

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import yaml

from consts.const import MEMORY_PROVIDER_PLUGINS_DIR
from nexent.memory.providers.base import (
    IngestibleMemoryProvider,
    SearchableMemoryProvider,
)

logger = logging.getLogger("memory_provider_plugin_loader")

if MEMORY_PROVIDER_PLUGINS_DIR:
    Path(MEMORY_PROVIDER_PLUGINS_DIR).mkdir(parents=True, exist_ok=True)


@dataclass
class PluginInfo:
    """Metadata for a loaded memory provider plugin."""

    name: str
    version: str
    description: str
    implements: list[str]
    config_schema: list[dict]
    plugin_dir: str
    entry_module: Any
    provider_class: type


_REQUIRED_MANIFEST_FIELDS = ("name", "version", "entry_point", "class_name", "implements")

_PROTOCOL_METHOD_MAP = {
    "searchable": "search",
    "ingestible": "ingest",
}


class PluginLoader:
    """Scan a plugin directory at startup and load all valid memory provider plugins."""

    def __init__(self, plugins_dir: str):
        self.plugins_dir = plugins_dir
        self._plugins: dict[str, PluginInfo] = {}

    def load_all(self) -> None:
        """Scan the plugin directory and load every valid plugin.

        Plugins that fail validation or import are logged as warnings and
        skipped without affecting other plugins or application startup.
        """
        plugins_path = Path(self.plugins_dir)
        if not plugins_path.is_dir():
            logger.info(
                "Plugin directory does not exist, skipping scan: %s",
                self.plugins_dir,
            )
            return

        success_count = 0
        failure_count = 0

        for child in sorted(plugins_path.iterdir()):
            if not child.is_dir():
                continue

            try:
                plugin_info = self._load_single_plugin(child)
                if plugin_info is not None:
                    self._plugins[plugin_info.name] = plugin_info
                    success_count += 1
                else:
                    failure_count += 1
            except Exception:
                logger.warning(
                    "Unexpected error loading plugin from %s",
                    child,
                    exc_info=True,
                )
                failure_count += 1

        logger.info(
            "Plugin scan complete: %d loaded, %d failed",
            success_count,
            failure_count,
        )

    def get_plugin(self, name: str) -> PluginInfo | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    def build_provider(
        self, name: str, config: dict
    ) -> Union[SearchableMemoryProvider, IngestibleMemoryProvider]:
        plugin = self._plugins.get(name)
        if plugin is None:
            raise ValueError(
                f"Memory provider plugin not found: {name!r}. "
                f"Available: {list(self._plugins.keys())}"
            )
        return plugin.provider_class(config)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_single_plugin(self, plugin_dir: Path) -> PluginInfo | None:
        manifest_path = plugin_dir / "plugin.yaml"

        manifest = self._parse_manifest(manifest_path, plugin_dir.name)
        if manifest is None:
            return None

        plugin_name = manifest["name"]
        entry_point = manifest["entry_point"]
        class_name = manifest["class_name"]
        implements = manifest["implements"]

        entry_file = plugin_dir / entry_point
        if not entry_file.is_file():
            logger.warning(
                "Plugin %r: entry_point file not found: %s",
                plugin_name,
                entry_file,
            )
            return None

        module = self._import_module(plugin_name, entry_file)
        if module is None:
            return None

        provider_class = getattr(module, class_name, None)
        if provider_class is None:
            logger.warning(
                "Plugin %r: class %r not found in module %s",
                plugin_name,
                class_name,
                entry_file,
            )
            return None

        if not self._validate_protocols(plugin_name, provider_class, implements):
            return None

        return PluginInfo(
            name=plugin_name,
            version=manifest.get("version", "0.0.0"),
            description=manifest.get("description", ""),
            implements=implements,
            config_schema=manifest.get("config_schema", []),
            plugin_dir=str(plugin_dir),
            entry_module=module,
            provider_class=provider_class,
        )

    def _parse_manifest(
        self, manifest_path: Path, dir_name: str
    ) -> dict | None:
        if not manifest_path.is_file():
            logger.warning(
                "Plugin directory %r: plugin.yaml not found", dir_name
            )
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = yaml.safe_load(fh)
        except yaml.YAMLError:
            logger.warning(
                "Plugin directory %r: plugin.yaml parse error",
                dir_name,
                exc_info=True,
            )
            return None

        if not isinstance(manifest, dict):
            logger.warning(
                "Plugin directory %r: plugin.yaml must be a YAML mapping",
                dir_name,
            )
            return None

        missing = [
            f for f in _REQUIRED_MANIFEST_FIELDS if f not in manifest
        ]
        if missing:
            logger.warning(
                "Plugin directory %r: plugin.yaml missing required fields: %s",
                dir_name,
                missing,
            )
            return None

        if not isinstance(manifest["implements"], list):
            logger.warning(
                "Plugin directory %r: 'implements' must be a list", dir_name
            )
            return None

        return manifest

    def _import_module(self, plugin_name: str, entry_file: Path) -> Any | None:
        module_name = f"memory_plugin_{plugin_name}"
        try:
            spec = importlib.util.spec_from_file_location(
                module_name, str(entry_file)
            )
            if spec is None or spec.loader is None:
                logger.warning(
                    "Plugin %r: failed to create module spec from %s",
                    plugin_name,
                    entry_file,
                )
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception:
            logger.warning(
                "Plugin %r: failed to import module %s",
                plugin_name,
                entry_file,
                exc_info=True,
            )
            return None

    def _validate_protocols(
        self, plugin_name: str, provider_class: type, implements: list[str]
    ) -> bool:
        for protocol_name in implements:
            required_method = _PROTOCOL_METHOD_MAP.get(protocol_name)
            if required_method is None:
                logger.warning(
                    "Plugin %r: unknown protocol %r in implements list",
                    plugin_name,
                    protocol_name,
                )
                return False

            if not callable(getattr(provider_class, required_method, None)):
                logger.warning(
                    "Plugin %r: class %s does not implement required method %r "
                    "for protocol %r",
                    plugin_name,
                    provider_class.__name__,
                    required_method,
                    protocol_name,
                )
                return False

        return True
