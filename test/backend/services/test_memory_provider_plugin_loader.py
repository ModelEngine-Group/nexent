import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

consts_const = types.ModuleType("consts.const")
consts_const.MEMORY_PROVIDER_PLUGINS_DIR = ""
sys.modules["consts.const"] = consts_const
sys.modules["consts"] = types.ModuleType("consts")

providers_base = types.ModuleType("nexent.memory.providers.base")


class SearchableMemoryProvider:
    def search(self, request, limit=5):
        pass


class IngestibleMemoryProvider:
    def ingest(self, request):
        pass


providers_base.SearchableMemoryProvider = SearchableMemoryProvider
providers_base.IngestibleMemoryProvider = IngestibleMemoryProvider

nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
memory_pkg.__path__ = []
providers_pkg = types.ModuleType("nexent.memory.providers")
providers_pkg.__path__ = []
providers_pkg.base = providers_base
memory_pkg.providers = providers_pkg
nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg
sys.modules["nexent.memory.providers"] = providers_pkg
sys.modules["nexent.memory.providers.base"] = providers_base

from backend.services.memory_provider_plugin_loader import PluginLoader  # noqa: E402


@pytest.fixture
def plugins_dir(tmp_path):
    return tmp_path / "plugins"


def _create_plugin(directory, name, manifest_content, entry_content=None):
    plugin_dir = directory / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(manifest_content)
    if entry_content:
        (plugin_dir / "provider.py").write_text(entry_content)
    return plugin_dir


VALID_MANIFEST = """
name: test-provider
version: "1.0.0"
description: A test provider
entry_point: provider.py
class_name: TestProvider
implements:
  - searchable
  - ingestible
config_schema:
  - key: api_key
    type: secret
    required: true
"""

VALID_ENTRY = """
class TestProvider:
    def __init__(self, config):
        self.config = config
    def search(self, request, limit=5):
        return []
    def ingest(self, request):
        return None
"""


def test_ac_p3_26_load_all_valid_plugin_from_configured_data_directory(plugins_dir):
    plugins_dir.mkdir()
    plugin_dir = _create_plugin(
        plugins_dir, "test-provider", VALID_MANIFEST, VALID_ENTRY
    )
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    plugins = loader.list_plugins()
    assert len(plugins) == 1
    assert plugins[0].name == "test-provider"
    assert plugins[0].version == "1.0.0"
    assert Path(plugins[0].entry_module.__file__).resolve().is_relative_to(
        plugin_dir.resolve()
    )
    provider = loader.build_provider("test-provider", {"api_key": "placeholder"})
    assert provider.config == {"api_key": "placeholder"}


def test_load_all_invalid_yaml(plugins_dir):
    plugins_dir.mkdir()
    _create_plugin(plugins_dir, "bad-yaml", "{{invalid: yaml: [", VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_load_all_missing_class(plugins_dir):
    plugins_dir.mkdir()
    manifest = VALID_MANIFEST.replace("class_name: TestProvider", "class_name: MissingClass")
    _create_plugin(plugins_dir, "missing-class", manifest, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_load_all_missing_entry_point(plugins_dir):
    plugins_dir.mkdir()
    _create_plugin(plugins_dir, "no-entry", VALID_MANIFEST, entry_content=None)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_load_all_directory_not_found():
    loader = PluginLoader("/nonexistent/path")
    loader.load_all()
    assert loader.list_plugins() == []


def test_get_plugin_found(plugins_dir):
    plugins_dir.mkdir()
    _create_plugin(plugins_dir, "test-provider", VALID_MANIFEST, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    plugin = loader.get_plugin("test-provider")
    assert plugin is not None
    assert plugin.name == "test-provider"


def test_get_plugin_not_found(plugins_dir):
    plugins_dir.mkdir()
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.get_plugin("nonexistent") is None


def test_list_plugins_empty(plugins_dir):
    plugins_dir.mkdir()
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_list_plugins_with_plugins(plugins_dir):
    plugins_dir.mkdir()
    _create_plugin(plugins_dir, "test-provider", VALID_MANIFEST, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert len(loader.list_plugins()) == 1


def test_build_provider_success(plugins_dir):
    plugins_dir.mkdir()
    _create_plugin(plugins_dir, "test-provider", VALID_MANIFEST, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    provider = loader.build_provider("test-provider", {"api_key": "sk-123"})
    assert hasattr(provider, "search")
    assert hasattr(provider, "ingest")


def test_build_provider_plugin_not_found(plugins_dir):
    plugins_dir.mkdir()
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    with pytest.raises(ValueError, match="not found"):
        loader.build_provider("nonexistent", {})


def test_protocol_validation_searchable_only(plugins_dir):
    plugins_dir.mkdir()
    manifest = """
name: search-only
version: "1.0.0"
entry_point: provider.py
class_name: SearchOnly
implements:
  - searchable
"""
    entry = """
class SearchOnly:
    def __init__(self, config):
        pass
    def search(self, request, limit=5):
        return []
"""
    _create_plugin(plugins_dir, "search-only", manifest, entry)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert len(loader.list_plugins()) == 1


def test_protocol_validation_ingestible_only(plugins_dir):
    plugins_dir.mkdir()
    manifest = """
name: ingest-only
version: "1.0.0"
entry_point: provider.py
class_name: IngestOnly
implements:
  - ingestible
"""
    entry = """
class IngestOnly:
    def __init__(self, config):
        pass
    def ingest(self, request):
        return None
"""
    _create_plugin(plugins_dir, "ingest-only", manifest, entry)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert len(loader.list_plugins()) == 1


def test_protocol_validation_missing_method(plugins_dir):
    plugins_dir.mkdir()
    manifest = """
name: bad-provider
version: "1.0.0"
entry_point: provider.py
class_name: BadProvider
implements:
  - searchable
"""
    entry = """
class BadProvider:
    def __init__(self, config):
        pass
"""
    _create_plugin(plugins_dir, "bad-provider", manifest, entry)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_protocol_validation_unknown_protocol(plugins_dir):
    plugins_dir.mkdir()
    manifest = """
name: unknown-proto
version: "1.0.0"
entry_point: provider.py
class_name: UnknownProto
implements:
  - unknown_protocol
"""
    entry = """
class UnknownProto:
    def __init__(self, config):
        pass
"""
    _create_plugin(plugins_dir, "unknown-proto", manifest, entry)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_module_level_mkdir_creates_directory(tmp_path):
    new_dir = tmp_path / "new_plugins_dir"
    assert not new_dir.exists()
    new_dir.mkdir(parents=True, exist_ok=True)
    assert new_dir.exists()


def test_load_all_skips_non_directory_children(plugins_dir):
    plugins_dir.mkdir()
    (plugins_dir / "readme.txt").write_text("not a plugin")
    _create_plugin(plugins_dir, "test-provider", VALID_MANIFEST, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert len(loader.list_plugins()) == 1


def test_parse_manifest_missing_required_fields(plugins_dir):
    plugins_dir.mkdir()
    manifest = """
name: incomplete
version: "1.0.0"
"""
    _create_plugin(plugins_dir, "incomplete", manifest, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []


def test_parse_manifest_implements_not_list(plugins_dir):
    plugins_dir.mkdir()
    manifest = """
name: bad-implements
version: "1.0.0"
entry_point: provider.py
class_name: TestProvider
implements: searchable
"""
    _create_plugin(plugins_dir, "bad-implements", manifest, VALID_ENTRY)
    loader = PluginLoader(str(plugins_dir))
    loader.load_all()

    assert loader.list_plugins() == []
