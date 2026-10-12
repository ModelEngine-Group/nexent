"""Offline tests for resource receipts and cleanup on failing Case setup."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

PATH = Path(__file__).resolve().parents[2] / 'automation/shared/factories/case_resources.py'


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.register = MagicMock()
        self.cleanup = AsyncMock(return_value=[])
        modules = {
            'shared': types.ModuleType('shared'),
            'shared.asset_registry': types.SimpleNamespace(register_asset=self.register),
            'shared.http': types.SimpleNamespace(client=MagicMock()),
            'shared.asset_cleanup': types.SimpleNamespace(cleanup_registered_assets=self.cleanup),
        }
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('journal_under_test', PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.identity = types.SimpleNamespace(id='tenant_a_admin')

    async def test_definition_is_registered_before_return(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {'definition_id': 42, 'values': [{'value_id': 71}]}
        api = types.SimpleNamespace(post=AsyncMock(return_value=response))
        journal = self.module.TagJournalClient(api, self.identity, 'CASE-1')
        self.assertIs(await journal.post('/tag-libraries/3/definitions'), response)
        self.assertEqual(self.register.call_count, 1)
        self.assertEqual(self.register.call_args_list[0].kwargs['owner_case_id'], 'CASE-1')
        self.assertEqual(self.register.call_args_list[0].kwargs['cleanup']['path'],
                         '/tag-libraries/3/definitions/42')

    async def test_conflict_does_not_register_foreign_resources(self):
        api = types.SimpleNamespace(post=AsyncMock(return_value=MagicMock(status_code=409)))
        await self.module.TagJournalClient(api, self.identity, 'CASE-1').post('/tag-libraries/3/definitions')
        self.register.assert_not_called()

    async def test_failure_cleans_only_own_case(self):
        with self.assertRaisesRegex(AssertionError, 'product failure'):
            async with self.module.cleanup_case('CASE-1'):
                raise AssertionError('product failure')
        self.cleanup.assert_awaited_once_with(owner_case_ids={'CASE-1'})

    async def test_cleanup_failure_is_not_success(self):
        self.cleanup.return_value = [{'result': 'ORPHANED'}]
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            async with self.module.cleanup_case('CASE-1'):
                pass

    async def test_primary_failure_preserved_when_cleanup_also_fails(self):
        self.cleanup.side_effect = RuntimeError('cleanup failed')
        with self.assertRaises(AssertionError) as captured:
            async with self.module.cleanup_case('CASE-1'):
                raise AssertionError('original')
        self.assertIn('cleanup also failed', captured.exception.__notes__[0])


if __name__ == '__main__':
    unittest.main()
