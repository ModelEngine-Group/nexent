# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Model selection and per-turn snapshots preserve the shared Agent boundary."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test_create_agent_info import create_agent_info_module as module
from test.backend.database.model_outlet_helpers import REGISTRY, profile  # noqa: F401


def test_exact_record_uses_frozen_profile_not_legacy_fields(monkeypatch):
    snapshot = object()
    record = {'tenant_id': 'tenant', 'model_repo': 'ignored', 'model_name': 'ignored'}
    restore = Mock(return_value=snapshot)
    resolved = Mock(return_value='resolved-config')
    monkeypatch.setattr(module, 'restore_model_snapshot', restore)
    monkeypatch.setattr(module, '_resolved_model_config', resolved)
    assert module.create_model_config_from_record(record) == 'resolved-config'
    restore.assert_called_once_with(record, 'tenant')
    resolved.assert_called_once_with(record, snapshot)


@pytest.mark.asyncio
async def test_model_list_skips_failed_rows_and_restores_default_aliases(monkeypatch):
    record = {'model_id': 12, 'profile_schema_version': 1, 'tenant_id': 'tenant'}
    monkeypatch.setattr(module, 'get_model_records', Mock(return_value=[{'model_id': 99}, record]))
    snapshot = object()
    monkeypatch.setattr(module, 'restore_model_snapshot', Mock(return_value=snapshot))
    monkeypatch.setattr(module, 'create_model_config_from_record', Mock(return_value='selected'))
    monkeypatch.setattr(module.tenant_config_manager, 'get_model_config', Mock(return_value=record))
    monkeypatch.setattr(module, '_resolved_model_config', Mock(side_effect=lambda row, snap, cite_name=None: cite_name))
    result = await module.create_model_config_list('tenant')
    assert result == ['selected', 'main_model', 'sub_model']
    module.create_model_config_from_record.assert_called_once_with(record)


def test_root_preferences_use_original_outlet_then_agent_values_without_mutating_children(monkeypatch):
    merge = Mock(return_value=SimpleNamespace(parameter_values={'temperature': 0}))
    parameters = ModuleType('services.agent_model_parameters')
    parameters.merge_runtime_model_parameters = merge
    monkeypatch.setitem(sys.modules, parameters.__name__, parameters)
    preferences = ModuleType('services.conversation_model_preferences_service')
    preferences.merge_model_preferences = Mock(side_effect=AssertionError('must use all explicit layers'))
    monkeypatch.setitem(sys.modules, preferences.__name__, preferences)
    original, active = object(), SimpleNamespace(outlet_id=12)
    root = SimpleNamespace(cite_name='root', resolved_profile=active, default_output_reserve_tokens=256)
    copy = SimpleNamespace(cite_name='private')
    root.model_copy = Mock(return_value=copy)
    child = SimpleNamespace(cite_name='child', resolved_profile=active)
    models, config = [root, child], SimpleNamespace(model_name='root')
    module.apply_root_model_preferences(models, config, {'12': {'temperature': 0}},
        outlet_profiles={12: original}, agent_overrides={'12': {'top_p': 0.8}})
    merge.assert_called_once_with(original, {'top_p': 0.8}, {'temperature': 0})
    assert models == [root, child, copy] and config.model_name == 'private'
    assert child.resolved_profile is active and root.resolved_profile is active
    assert root.model_copy.call_args.kwargs['update']['default_output_reserve_tokens'] == 256


@pytest.mark.asyncio
async def test_run_captures_database_snapshot_and_validates_output_before_config_assembly(monkeypatch, profile):
    class Prepared(RuntimeError):
        pass

    registry = ModuleType('nexent.core.model_service.registry')
    registry.model_service_references = lambda: REGISTRY
    monkeypatch.setitem(sys.modules, registry.__name__, registry)
    preferences = ModuleType('services.conversation_model_preferences_service')
    preferences.merge_model_preferences = Mock(return_value=SimpleNamespace(parameter_values={'max_output_tokens': 128}))
    monkeypatch.setitem(sys.modules, preferences.__name__, preferences)
    selected = SimpleNamespace(cite_name='selected', resolved_profile=profile)
    monkeypatch.setattr(module, '_build_run_workspace', Mock(return_value='/controlled/workspace'))
    monkeypatch.setattr(module, '_ensure_agent_reasoning_snapshot', Mock())
    monkeypatch.setattr(module, 'join_minio_file_description_to_query', AsyncMock(return_value='processed'))
    monkeypatch.setattr(module, 'create_model_config_list', AsyncMock(return_value=[selected]))
    monkeypatch.setattr(module, 'search_agent_info_by_agent_id', Mock(return_value={'model_ids': [12]}))
    monkeypatch.setattr(module, '_select_agent_model_id', Mock(return_value=12))
    prepare = AsyncMock(side_effect=Prepared())
    monkeypatch.setattr(module, 'create_agent_config', prepare)
    before = profile.model_dump()
    with pytest.raises(Prepared):
        await module.create_agent_run_info(agent_id=1, minio_files=[], query='input', history=[],
            user_id='user', tenant_id='tenant-one', language='en', is_debug=True,
            model_parameter_preferences={'12': {'max_output_tokens': 128}})
    kwargs = prepare.call_args.kwargs
    assert kwargs['runtime_output_tokens'] == 128
    assert kwargs['runtime_model_records'][12]['model_name'] == 'Exact/Model'
    assert kwargs['runtime_model_records'][12]['tenant_id'] == 'tenant-one'
    assert 'api_key' not in kwargs['runtime_model_records'][12]
    preferences.merge_model_preferences.assert_called_once_with(profile, {'max_output_tokens': 128})
    assert profile.model_dump() == before


@pytest.mark.parametrize("preferences", [{}, {"99": {"temperature": 0}}])
def test_missing_preferences_leave_model_identity_unchanged(monkeypatch, preferences):
    service = ModuleType('services.conversation_model_preferences_service')
    service.merge_model_preferences = Mock(side_effect=AssertionError('no matching preference'))
    monkeypatch.setitem(sys.modules, service.__name__, service)
    root = SimpleNamespace(cite_name='root', resolved_profile=SimpleNamespace(outlet_id=12))
    models = [root]
    config = SimpleNamespace(model_name='root')
    module.apply_root_model_preferences(models, config, preferences)
    assert models == [root] and config.model_name == 'root'


def test_saved_profile_preferences_work_without_original_catalog_lookup(monkeypatch):
    service = ModuleType('services.conversation_model_preferences_service')
    resolved = SimpleNamespace(parameter_values={'max_output_tokens': 512})
    service.merge_model_preferences = Mock(return_value=resolved)
    monkeypatch.setitem(sys.modules, service.__name__, service)
    profile = SimpleNamespace(outlet_id=12)
    root = SimpleNamespace(cite_name='root', resolved_profile=profile, default_output_reserve_tokens=256)
    copied = SimpleNamespace(cite_name='private')
    root.model_copy = Mock(return_value=copied)
    models = [SimpleNamespace(cite_name='child', resolved_profile=None), root]
    config = SimpleNamespace(model_name='root')
    module.apply_root_model_preferences(models, config, {'12': {'temperature': 0}})
    service.merge_model_preferences.assert_called_once_with(profile, {'temperature': 0})
    assert models[-1] is copied and config.model_name == 'private'
    assert root.model_copy.call_args.kwargs['update']['default_output_reserve_tokens'] == 512


@pytest.mark.asyncio
async def test_failed_default_does_not_supply_legacy_aliases(monkeypatch):
    selected = {"model_id": 12, "profile_schema_version": 1}
    monkeypatch.setattr(module, "get_model_records", Mock(return_value=[selected]))
    monkeypatch.setattr(module, "create_model_config_from_record", Mock(return_value="selected"))
    monkeypatch.setattr(module.tenant_config_manager, "get_model_config", Mock(return_value={"model_id": 99, "profile_schema_version": None}))
    restore = Mock(side_effect=AssertionError("failed default must not be restored"))
    monkeypatch.setattr(module, "restore_model_snapshot", restore)
    assert await module.create_model_config_list("tenant") == ["selected"]
    restore.assert_not_called()
