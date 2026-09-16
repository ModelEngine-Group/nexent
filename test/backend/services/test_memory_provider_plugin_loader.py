import shutil
import sys
import types
from concurrent.futures import ThreadPoolExecutor
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

from backend.services import memory_provider_plugin_loader as plugin_loader_module
from backend.services.memory_provider_plugin_loader import PluginLoader


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


def _manifest_for(name):
    return VALID_MANIFEST.replace("name: test-provider", f"name: {name}")


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


def test_ac_001_builtin_plugin_is_discovered_when_external_directory_is_empty(tmp_path):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    _create_plugin(builtin_dir, "mem0", _manifest_for("mem0"), VALID_ENTRY)

    loader = PluginLoader(
        str(external_dir), builtin_plugins_dir=str(builtin_dir)
    )
    loader.load_all()

    assert [plugin.name for plugin in loader.list_plugins()] == ["mem0"]


def test_include_builtin_plugins_uses_default_builtin_directory(tmp_path, monkeypatch):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    monkeypatch.setattr(
        plugin_loader_module,
        "BUILTIN_MEMORY_PROVIDER_PLUGINS_DIR",
        builtin_dir,
    )

    loader = PluginLoader(str(external_dir), include_builtin_plugins=True)

    assert loader.builtin_plugins_dir == str(builtin_dir)
    assert loader._plugin_sources == [
        ("builtin", builtin_dir),
        ("external", external_dir),
    ]


def test_empty_external_directory_argument_only_registers_builtin_source(tmp_path):
    builtin_dir = tmp_path / "builtin"

    loader = PluginLoader("", builtin_plugins_dir=str(builtin_dir))

    assert loader._plugin_sources == [("builtin", builtin_dir)]


def test_same_builtin_and_external_directory_is_scanned_once(tmp_path):
    shared_dir = tmp_path / "shared"

    loader = PluginLoader(
        str(shared_dir),
        builtin_plugins_dir=str(shared_dir),
    )

    assert loader._plugin_sources == [("builtin", shared_dir)]


def test_ac_002_builtin_and_external_plugins_are_merged(tmp_path):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    _create_plugin(builtin_dir, "mem0", _manifest_for("mem0"), VALID_ENTRY)
    _create_plugin(
        external_dir,
        "partner-memory",
        _manifest_for("partner-memory"),
        VALID_ENTRY,
    )

    loader = PluginLoader(
        str(external_dir), builtin_plugins_dir=str(builtin_dir)
    )
    loader.load_all()

    assert {plugin.name for plugin in loader.list_plugins()} == {
        "mem0",
        "partner-memory",
    }


def test_ac_003_external_plugin_overrides_builtin_and_removal_restores_builtin(
    tmp_path, caplog
):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    builtin_entry = VALID_ENTRY.replace(
        "class TestProvider:", 'class TestProvider:\n    source = "builtin"'
    )
    external_entry = VALID_ENTRY.replace(
        "class TestProvider:", 'class TestProvider:\n    source = "external"'
    )
    _create_plugin(
        builtin_dir, "shared-provider", _manifest_for("shared-provider"), builtin_entry
    )
    external_plugin_dir = _create_plugin(
        external_dir,
        "shared-provider",
        _manifest_for("shared-provider"),
        external_entry,
    )
    loader = PluginLoader(
        str(external_dir), builtin_plugins_dir=str(builtin_dir)
    )

    loader.load_all()
    assert loader.get_plugin("shared-provider").provider_class.source == "external"
    assert "overrides plugin from builtin" in caplog.text

    shutil.rmtree(external_plugin_dir)
    assert loader.get_plugin("shared-provider").provider_class.source == "builtin"


def test_ac_008_new_external_plugin_is_discovered_without_reloading_process(tmp_path):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    loader = PluginLoader(
        str(external_dir), builtin_plugins_dir=str(builtin_dir)
    )
    loader.load_all()
    loader_identity = id(loader)

    _create_plugin(
        external_dir,
        "hot-added",
        _manifest_for("hot-added"),
        VALID_ENTRY,
    )

    assert loader.get_plugin("hot-added") is not None
    assert id(loader) == loader_identity


def test_ac_004_invalid_external_plugin_does_not_hide_builtin_plugin(tmp_path):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    _create_plugin(builtin_dir, "mem0", _manifest_for("mem0"), VALID_ENTRY)
    _create_plugin(
        external_dir,
        "incomplete-provider",
        _manifest_for("incomplete-provider"),
        entry_content=None,
    )
    loader = PluginLoader(
        str(external_dir), builtin_plugins_dir=str(builtin_dir)
    )

    loader.load_all()

    assert [plugin.name for plugin in loader.list_plugins()] == ["mem0"]


def test_ac_008_external_plugin_update_is_discovered_without_restart(tmp_path):
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    entry_v1 = VALID_ENTRY.replace(
        "class TestProvider:", 'class TestProvider:\n    version = "v1"'
    )
    plugin_dir = _create_plugin(
        external_dir,
        "hot-updated",
        _manifest_for("hot-updated"),
        entry_v1,
    )
    loader = PluginLoader(str(external_dir))
    loader.load_all()
    assert loader.get_plugin("hot-updated").provider_class.version == "v1"

    entry_v2 = entry_v1.replace('version = "v1"', 'version = "version-two"')
    (plugin_dir / "provider.py").write_text(entry_v2)

    assert loader.get_plugin("hot-updated").provider_class.version == "version-two"


def test_ac_010_unchanged_directories_do_not_reimport_plugins(tmp_path, monkeypatch):
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    _create_plugin(
        external_dir,
        "stable-provider",
        _manifest_for("stable-provider"),
        VALID_ENTRY,
    )
    loader = PluginLoader(str(external_dir))
    import_count = 0
    original_import = loader._import_module

    def counting_import(plugin_name, entry_file):
        nonlocal import_count
        import_count += 1
        return original_import(plugin_name, entry_file)

    monkeypatch.setattr(loader, "_import_module", counting_import)
    loader.load_all()

    loader.list_plugins()
    loader.get_plugin("stable-provider")
    loader.build_provider("stable-provider", {})
    assert import_count == 1


def test_ac_011_concurrent_refresh_exposes_complete_registry(tmp_path):
    builtin_dir = tmp_path / "builtin"
    external_dir = tmp_path / "external"
    builtin_dir.mkdir()
    external_dir.mkdir()
    _create_plugin(builtin_dir, "mem0", _manifest_for("mem0"), VALID_ENTRY)
    loader = PluginLoader(
        str(external_dir), builtin_plugins_dir=str(builtin_dir)
    )
    loader.load_all()
    _create_plugin(
        external_dir,
        "hot-added",
        _manifest_for("hot-added"),
        VALID_ENTRY,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: {plugin.name for plugin in loader.list_plugins()},
                range(32),
            )
        )

    assert all(result == {"mem0", "hot-added"} for result in results)


def test_fingerprint_records_unavailable_entry(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    unavailable = plugins_dir / "unavailable"
    loader = PluginLoader(str(plugins_dir))
    original_stat = Path.stat

    monkeypatch.setattr(Path, "rglob", lambda self, pattern: [unavailable])

    def failing_stat(path):
        if path == unavailable:
            raise OSError("entry unavailable")
        return original_stat(path)

    monkeypatch.setattr(Path, "stat", failing_stat)

    fingerprint = loader._calculate_fingerprint()

    assert (str(unavailable), "unavailable", "OSError") in fingerprint


def test_fingerprint_records_unavailable_source(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    loader = PluginLoader(str(plugins_dir))

    monkeypatch.setattr(
        Path,
        "rglob",
        lambda self, pattern: (_ for _ in ()).throw(OSError("source unavailable")),
    )

    assert ("unavailable", "OSError") in loader._calculate_fingerprint()


def test_scan_sources_skips_directory_when_listing_fails(tmp_path, monkeypatch, caplog):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    loader = PluginLoader(str(plugins_dir))

    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: (_ for _ in ()).throw(OSError("listing failed")),
    )

    plugins, loaded_count, failure_count = loader._scan_sources()

    assert plugins == {}
    assert loaded_count == 0
    assert failure_count == 1
    assert "cannot be read" in caplog.text


def test_scan_sources_isolates_unexpected_plugin_error(tmp_path, monkeypatch, caplog):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "broken"
    plugin_dir.mkdir(parents=True)
    loader = PluginLoader(str(plugins_dir))

    monkeypatch.setattr(
        loader,
        "_load_single_plugin",
        lambda child: (_ for _ in ()).throw(RuntimeError("unexpected failure")),
    )

    plugins, loaded_count, failure_count = loader._scan_sources()

    assert plugins == {}
    assert loaded_count == 0
    assert failure_count == 1
    assert "Unexpected error loading plugin" in caplog.text


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
