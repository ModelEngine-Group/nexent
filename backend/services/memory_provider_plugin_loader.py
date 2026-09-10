"""Plugin loader for external memory providers.

Scans a configured directory for memory provider plugins, validates their
plugin.yaml manifests and protocol conformance, and provides factory methods
to instantiate provider classes at runtime.
"""

import importlib.util
import logging
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

BUILTIN_MEMORY_PROVIDER_PLUGINS_DIR = (
    Path(__file__).resolve().parent.parent / "memory_provider_plugins"
)


class PluginLoader:
    """Discover memory provider plugins from ordered, hot-reloadable directories."""

    def __init__(
        self,
        plugins_dir: str,
        builtin_plugins_dir: str | None = None,
        include_builtin_plugins: bool = False,
    ):
        if include_builtin_plugins and builtin_plugins_dir is None:
            builtin_plugins_dir = str(BUILTIN_MEMORY_PROVIDER_PLUGINS_DIR)
        self.plugins_dir = plugins_dir
        self.builtin_plugins_dir = builtin_plugins_dir
        self._plugin_sources: list[tuple[str, Path]] = []
        if builtin_plugins_dir:
            self._plugin_sources.append(("builtin", Path(builtin_plugins_dir)))
        if plugins_dir:
            external_path = Path(plugins_dir)
            if not self._plugin_sources or external_path != self._plugin_sources[0][1]:
                self._plugin_sources.append(("external", external_path))
        self._plugins: dict[str, PluginInfo] = {}
        self._fingerprint: tuple | None = None
        self._refresh_lock = threading.RLock()

    def load_all(self) -> None:
        """Force a scan of every configured directory.

        Plugins that fail validation or import are logged as warnings and
        skipped without affecting other plugins or application startup.
        """
        self._refresh(force=True)

    def refresh_if_changed(self) -> bool:
        """Refresh the registry when plugin directory contents have changed."""
        return self._refresh(force=False)

    def get_plugin(self, name: str) -> PluginInfo | None:
        self.refresh_if_changed()
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginInfo]:
        self.refresh_if_changed()
        return list(self._plugins.values())

    def build_provider(
        self, name: str, config: dict
    ) -> SearchableMemoryProvider | IngestibleMemoryProvider:
        self.refresh_if_changed()
        plugin = self._plugins.get(name)
        if plugin is None:
            raise ValueError(
                f"Memory provider plugin not found: {name!r}. "
                f"Available: {list(self._plugins.keys())}"
            )
        return plugin.provider_class(config)

    # ------------------------------------------------------------------
    # Discovery and refresh
    # ------------------------------------------------------------------

    def _refresh(self, force: bool) -> bool:
        fingerprint = self._calculate_fingerprint()
        if not force and fingerprint == self._fingerprint:
            return False

        with self._refresh_lock:
            fingerprint = self._calculate_fingerprint()
            if not force and fingerprint == self._fingerprint:
                return False

            plugins, loaded_count, failure_count = self._scan_sources()
            self._plugins = plugins
            self._fingerprint = self._calculate_fingerprint()
            logger.info(
                "Plugin scan complete: %d loaded, %d failed, %d available",
                loaded_count,
                failure_count,
                len(plugins),
            )
            return True

    def _calculate_fingerprint(self) -> tuple:
        entries: list[tuple] = []
        for source_name, plugins_path in self._plugin_sources:
            entries.append((source_name, str(plugins_path)))
            try:
                if not plugins_path.is_dir():
                    entries.append(("missing",))
                    continue
                for path in sorted(plugins_path.rglob("*")):
                    try:
                        stat = path.stat()
                        entries.append(
                            (
                                str(path.relative_to(plugins_path)),
                                path.is_dir(),
                                stat.st_size,
                                stat.st_mtime_ns,
                                stat.st_ctime_ns,
                            )
                        )
                    except OSError as exc:
                        entries.append((str(path), "unavailable", type(exc).__name__))
            except OSError as exc:
                entries.append(("unavailable", type(exc).__name__))
        return tuple(entries)

    def _scan_sources(self) -> tuple[dict[str, PluginInfo], int, int]:
        plugins: dict[str, PluginInfo] = {}
        plugin_sources: dict[str, str] = {}
        loaded_count = 0
        failure_count = 0

        for source_name, plugins_path in self._plugin_sources:
            if not plugins_path.is_dir():
                logger.info(
                    "Plugin directory does not exist, skipping %s scan: %s",
                    source_name,
                    plugins_path,
                )
                continue

            try:
                children = sorted(plugins_path.iterdir())
            except OSError:
                logger.warning(
                    "Plugin directory cannot be read, skipping %s scan: %s",
                    source_name,
                    plugins_path,
                    exc_info=True,
                )
                failure_count += 1
                continue

            for child in children:
                if not child.is_dir():
                    continue

                try:
                    plugin_info = self._load_single_plugin(child)
                    if plugin_info is None:
                        failure_count += 1
                        continue

                    previous_source = plugin_sources.get(plugin_info.name)
                    if previous_source is not None:
                        logger.warning(
                            "Plugin %r from %s overrides plugin from %s",
                            plugin_info.name,
                            source_name,
                            previous_source,
                        )
                    plugins[plugin_info.name] = plugin_info
                    plugin_sources[plugin_info.name] = source_name
                    loaded_count += 1
                except Exception:
                    logger.warning(
                        "Unexpected error loading plugin from %s",
                        child,
                        exc_info=True,
                    )
                    failure_count += 1

        return plugins, loaded_count, failure_count

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
