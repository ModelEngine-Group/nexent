# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-COORD-02: current-actor storage composition owns its handles."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge import STORAGE_LEDGER_DATASET, STORAGE_LEDGER_HISTORY_DATASET
from contracts.knowledge_deletion import DELETION_DATASET
from nexent.storage.errors import ScopeDenied

from infrastructure import knowledge_deletion as module
from infrastructure.object_storage import composition
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def setup(monkeypatch):
    engine, records, resources, objects = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(module, 'record_engine', Mock(return_value=engine))
    monkeypatch.setattr(module, 'bind_deletion_records', Mock(return_value=records))
    monkeypatch.setattr(module, 'bind_cleanse_resources', Mock(return_value=resources))
    monkeypatch.setattr(composition, 'bind_source_objects', Mock(return_value=objects))
    actor = SimpleNamespace(user_id='editor-b', tenant_id='tenant-a')
    row = {'tenant_id': actor.tenant_id, 'object_name': 'kb/source.txt', 'bucket_name': 'bucket'}
    return SimpleNamespace(**locals())


def test_records_grant_only_management_current_actor_and_owned_ports_are_closed(setup):
    s = setup
    with module.knowledge_deletion_ports(s.actor, context=context()) as (records, resources):
        assert records is s.records and resources is s.resources
        scope = module.bind_deletion_records.call_args.args[0]
        assert scope.service_role == 'management' and scope.actor_id == 'editor-b'
        assert scope.tenant_id == 'tenant-a' and scope.system is False
        assert scope.namespaces == {DELETION_DATASET, STORAGE_LEDGER_DATASET, STORAGE_LEDGER_HISTORY_DATASET}
    s.records.close.assert_called_once()
    s.resources.close.assert_called_once()
    s.engine.dispose.assert_called_once()


def test_source_grant_is_exact_current_actor_and_closed_on_failure(setup):
    s = setup
    with pytest.raises(ValueError), module.deletion_source_objects(s.row, s.actor, context=context()) as objects:
        assert objects is s.objects
        composition.bind_source_objects.assert_called_once_with('tenant-a', 'editor-b', 'kb/source.txt', 'bucket')
        raise ValueError('controlled')
    s.objects.close.assert_called_once()


def test_no_object_uses_no_storage_client(setup):
    s = setup
    with module.deletion_source_objects({**s.row, 'object_name': None}, s.actor, context=context()) as objects:
        assert objects is None
    composition.bind_source_objects.assert_not_called()


def test_other_tenant_source_cannot_get_an_object_handle(setup):
    s = setup
    with pytest.raises(ScopeDenied), module.deletion_source_objects({**s.row, 'tenant_id': 'other'}, s.actor, context=context()):
        pytest.fail('cross-tenant source was granted')
    composition.bind_source_objects.assert_not_called()


def test_partial_composition_failure_closes_records_and_engine(setup, monkeypatch):
    s = setup
    monkeypatch.setattr(module, 'bind_cleanse_resources', Mock(side_effect=ScopeDenied()))
    with pytest.raises(ScopeDenied), module.knowledge_deletion_ports(s.actor, context=context()):
        pytest.fail('failed composition yielded')
    s.records.close.assert_called_once()
    s.engine.dispose.assert_called_once()
