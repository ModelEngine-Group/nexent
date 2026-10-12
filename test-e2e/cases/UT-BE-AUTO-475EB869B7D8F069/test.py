import logging
import textwrap
from pathlib import Path

import pytest
import yaml

from services.memory_provider_plugin_loader import PluginInfo, PluginLoader

pytestmark = [
    pytest.mark.case_id('UT-BE-AUTO-475EB869B7D8F069'),
    pytest.mark.stage('D1'),
]

_BASE_FIELDS = {
    'name': 'some_plugin',
    'version': '1.0.0',
    'description': 'a test provider',
    'entry_point': 'provider.py',
    'class_name': 'ValidProvider',
    'implements': ['searchable', 'ingestible'],
    'config_schema': [{'name': 'api_key', 'type': 'string', 'required': True}],
}

_VALID_PROVIDER = textwrap.dedent(
    '''
    class ValidProvider:
        def __init__(self, config):
            self.config = config

        def search(self, request, limit=5, filters=None):
            return []

        def ingest(self, request):
            return None
    '''
)

_INGEST_ONLY_PROVIDER = textwrap.dedent(
    '''
    class ValidProvider:
        def __init__(self, config):
            self.config = config

        def ingest(self, request):
            return None
    '''
)

_SEARCH_ONLY_PROVIDER = textwrap.dedent(
    '''
    class ValidProvider:
        def __init__(self, config):
            self.config = config

        def search(self, request, limit=5, filters=None):
            return []
    '''
)

_IMPORT_BOOM_PROVIDER = '''
raise RuntimeError('import boom')
'''


def _manifest(**overrides):
    fields = dict(_BASE_FIELDS)
    fields.update(overrides)
    return yaml.safe_dump(fields, sort_keys=False)


def _manifest_without(missing):
    fields = dict(_BASE_FIELDS)
    fields.pop(missing)
    return yaml.safe_dump(fields, sort_keys=False)


def _write_plugin(root, name, manifest_text, provider_src=_VALID_PROVIDER):
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / 'plugin.yaml').write_text(manifest_text, encoding='utf-8')
    (plugin_dir / 'provider.py').write_text(provider_src, encoding='utf-8')
    return plugin_dir


def test_plugin_loader_core_flow(tmp_path, caplog):
    secret = 'S3CR3T-API-KEY-7f3a9c1d'

    valid_root = tmp_path / 'a_valid'
    _write_plugin(valid_root, 'valid_provider', _manifest(name='valid_provider', description='a valid provider'))
    loader = PluginLoader(str(valid_root))
    loader.load_all()
    plugins = loader.list_plugins()
    assert len(plugins) == 1
    info = plugins[0]
    assert isinstance(info, PluginInfo)
    assert info.name == 'valid_provider'
    assert info.version == '1.0.0'
    assert info.implements == ['searchable', 'ingestible']
    assert info.config_schema == [{'name': 'api_key', 'type': 'string', 'required': True}]
    assert info.description == 'a valid provider'
    assert info.plugin_dir == str(valid_root / 'valid_provider')
    assert info.provider_class.__name__ == 'ValidProvider'

    invalid_root = tmp_path / 'b_invalid'
    _write_plugin(invalid_root, 'valid_provider', _manifest(name='valid_provider'))
    _write_plugin(invalid_root, 'missing_name', _manifest_without('name'))
    _write_plugin(invalid_root, 'missing_version', _manifest_without('version'))
    _write_plugin(invalid_root, 'missing_entry_point', _manifest_without('entry_point'))
    _write_plugin(invalid_root, 'missing_class_name', _manifest_without('class_name'))
    _write_plugin(invalid_root, 'missing_implements', _manifest_without('implements'))
    _write_plugin(invalid_root, 'implements_not_list', _manifest(name='implements_not_list', implements='searchable'))
    _write_plugin(invalid_root, 'yaml_parse_error', 'implements: [searchable')
    _write_plugin(invalid_root, 'not_mapping', '[one, two, three]')
    _write_plugin(invalid_root, 'unknown_protocol', _manifest(name='unknown_protocol', implements=['searchable', 'unknown_protocol']))
    _write_plugin(invalid_root, 'no_search', _manifest(name='no_search', implements=['searchable']), provider_src=_INGEST_ONLY_PROVIDER)
    _write_plugin(invalid_root, 'no_ingest', _manifest(name='no_ingest', implements=['ingestible']), provider_src=_SEARCH_ONLY_PROVIDER)
    _write_plugin(invalid_root, 'missing_class', _manifest(name='missing_class', class_name='MissingClass'))
    _write_plugin(invalid_root, 'import_boom', _manifest(name='import_boom'), provider_src=_IMPORT_BOOM_PROVIDER)
    missing_file_dir = invalid_root / 'missing_entry_file'
    missing_file_dir.mkdir(parents=True, exist_ok=True)
    (missing_file_dir / 'plugin.yaml').write_text(_manifest(name='missing_entry_file'), encoding='utf-8')
    loader2 = PluginLoader(str(invalid_root))
    loader2.load_all()
    assert {p.name for p in loader2.list_plugins()} == {'valid_provider'}

    hot_root = tmp_path / 'c_hot'
    _write_plugin(hot_root, 'first', _manifest(name='first'))
    loader3 = PluginLoader(str(hot_root))
    loader3.load_all()
    assert {p.name for p in loader3.list_plugins()} == {'first'}
    assert loader3.refresh_if_changed() is False
    assert {p.name for p in loader3.list_plugins()} == {'first'}
    _write_plugin(hot_root, 'second', _manifest(name='second'))
    assert loader3.refresh_if_changed() is True
    assert {p.name for p in loader3.list_plugins()} == {'first', 'second'}

    builtin_root = tmp_path / 'builtin'
    external_root = tmp_path / 'external'
    _write_plugin(builtin_root, 'shared_plugin', _manifest(name='shared_plugin', version='1.0.0'))
    _write_plugin(external_root, 'shared_plugin', _manifest(name='shared_plugin', version='2.0.0'))
    loader4 = PluginLoader(str(external_root), builtin_plugins_dir=str(builtin_root), include_builtin_plugins=True)
    with caplog.at_level(logging.WARNING):
        loader4.load_all()
    plugins4 = loader4.list_plugins()
    assert [p.name for p in plugins4] == ['shared_plugin']
    assert plugins4[0].version == '2.0.0'
    assert any('overrides' in r.message and 'shared_plugin' in r.message for r in caplog.records)

    loader5 = PluginLoader(str(valid_root))
    loader5.load_all()
    assert loader5.get_plugin('does_not_exist') is None
    with pytest.raises(ValueError) as exc_info:
        loader5.build_provider('does_not_exist', {})
    message = str(exc_info.value)
    assert 'Available' in message
    assert 'valid_provider' in message

    loader6 = PluginLoader(str(valid_root))
    with caplog.at_level(logging.DEBUG):
        loader6.load_all()
        built = loader6.build_provider('valid_provider', {'api_key': secret, 'password': secret, 'token': secret})
    assert built is not None
    assert secret not in caplog.text
