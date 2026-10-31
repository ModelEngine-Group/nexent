"""Fallback cleanup must preserve declared query parameters and ownership."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

PATH = Path(__file__).resolve().parents[2] / 'automation/shared/asset_cleanup.py'


class CleanupQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_relation_cleanup_forwards_query_parameters(self):
        params = {'local_agent_id': 42, 'external_agent_id': 71}
        assets = {'owned_a2a_relations': {'42': {
            'source': 'dynamic', 'state': 'READY', 'owner_case_id': 'CASE-1',
            'cleanup': {'identity': 'tenant_a_admin', 'service': 'config',
                        'method': 'DELETE', 'path': '/a2a/client/relations', 'params': params},
        }}, 'foreign': {'99': {
            'source': 'dynamic', 'state': 'READY', 'owner_case_id': 'CASE-2',
            'cleanup': {'service': 'config', 'path': '/agent/99'},
        }}}
        api = types.SimpleNamespace(request=AsyncMock(return_value=MagicMock(status_code=200)))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=api)
        context.__aexit__ = AsyncMock(return_value=False)
        mark = MagicMock()
        modules = {
            'shared': types.ModuleType('shared'),
            'shared.asset_registry': types.SimpleNamespace(
                all_registered_assets=lambda: assets, mark_asset_state=mark, runtime_dir=MagicMock()),
            'shared.auth': types.SimpleNamespace(sign_in=AsyncMock(return_value=types.SimpleNamespace(access_token='test-token'))),
            'shared.config': types.SimpleNamespace(load_yaml=MagicMock()),
            'shared.http': types.SimpleNamespace(client=MagicMock(return_value=context)),
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('cleanup_query_under_test', PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            rows = await module.cleanup_registered_assets(owner_case_ids={'CASE-1'})
        api.request.assert_awaited_once_with('DELETE', '/a2a/client/relations', json=None, params=params)
        self.assertEqual([row['result'] for row in rows], ['DELETED'])
        mark.assert_called_once_with('owned_a2a_relations', '42', 'DELETED')


if __name__ == '__main__':
    unittest.main()
