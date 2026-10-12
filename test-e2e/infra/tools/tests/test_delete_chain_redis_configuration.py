"""The delete-chain fixture configures aliases and later Celery imports alike."""
from pathlib import Path
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
import nexent_formal_pytest as fixtures
from shared.factories import redis_target


class RedisConfigurationTests(unittest.TestCase):
    def test_current_public_helper_uses_the_supplier_patched_by_the_case(self):
        repo = Path(__file__).resolve().parents[4]
        package = ModuleType('data_process')
        package.__path__ = [str(repo / 'backend/data_process')]
        lookup = Mock(return_value={'status': 'DELETE_REQUESTED'})
        supplier = Mock(return_value=SimpleNamespace(
            is_document_delete_requested=Mock(side_effect=RuntimeError('controlled Redis outage'))))
        modules = {
            'data_process': package,
            'data_process.app': SimpleNamespace(app=Mock()),
            'services.redis_service': SimpleNamespace(get_redis_service=supplier),
            'database.knowledge_file_lifecycle_db': SimpleNamespace(get_file_record=lookup),
        }
        spec = importlib.util.spec_from_file_location(
            'data_process.delete_fence_fixture_utils', repo / 'backend/data_process/utils.py')
        utility = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(utility)
            args = {'file_id': 'owned-fixture', 'tenant_id': 'fixture-tenant',
                    'index_name': 'fixture-index', 'source': 'fixture-source'}
            self.assertTrue(utility.is_document_delete_requested(**args))
            lookup.assert_called_once_with(file_id=args['file_id'], tenant_id=args['tenant_id'],
                                           index_name=args['index_name'], include_hidden=True)
            lookup.return_value = None
            self.assertFalse(utility.is_document_delete_requested(**args))
            lookup.side_effect = RuntimeError('controlled lifecycle outage')
            self.assertFalse(utility.is_document_delete_requested(**args))
            lookup.reset_mock()
            supplier.return_value.is_document_delete_requested.side_effect = None
            supplier.return_value.is_document_delete_requested.return_value = False
            self.assertFalse(utility.is_document_delete_requested(**args))
            lookup.assert_not_called()

    def test_canonical_and_service_constants_share_target_and_are_restored(self):
        service = SimpleNamespace(REDIS_URL=None, REDIS_BACKEND_URL=None, _redis_service=None)
        canonical = SimpleNamespace(REDIS_URL=None, REDIS_BACKEND_URL=None)
        request = SimpleNamespace(node=SimpleNamespace(
            iter_markers=lambda name: [SimpleNamespace(args=['API-AUTO-2B3A078E3CD1B151'])]))
        general, backend = 'redis://example.test/0', 'redis://example.test/1'
        with patch.dict(sys.modules, {'services': SimpleNamespace(redis_service=service),
                                     'consts': SimpleNamespace(const=canonical)}), \
                patch.object(redis_target, 'deployed_redis_urls', return_value=(general, backend)):
            with pytest.MonkeyPatch.context() as monkeypatch:
                generator = fixtures.isolated_migration_database.__wrapped__(request, monkeypatch)
                next(generator)
                self.assertEqual((service.REDIS_URL, service.REDIS_BACKEND_URL), (general, backend))
                self.assertEqual((canonical.REDIS_URL, canonical.REDIS_BACKEND_URL), (general, backend))
                with self.assertRaises(StopIteration):
                    next(generator)
            self.assertIsNone(service.REDIS_URL)
            self.assertIsNone(canonical.REDIS_URL)

    def test_no_redis_configuration_for_unrelated_case(self):
        request = SimpleNamespace(node=SimpleNamespace(
            iter_markers=lambda name: [SimpleNamespace(args=['unrelated-case'])]))
        with patch.object(redis_target, 'deployed_redis_urls') as resolve:
            with pytest.MonkeyPatch.context() as monkeypatch:
                generator = fixtures.isolated_migration_database.__wrapped__(request, monkeypatch)
                next(generator)
                with self.assertRaises(StopIteration):
                    next(generator)
            resolve.assert_not_called()
