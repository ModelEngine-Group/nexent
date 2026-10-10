"""Controlled provider gates; these are not substitutes for CMSR integration cases."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[2] / 'environment/services/test-assets/cmsr_provider.py'
spec = importlib.util.spec_from_file_location('cmsr_provider_under_test', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_and_semantic_sequences(self):
        for mode in ('transport', 'semantic'):
            item = module.Scenario(mode)
            nonce = 'a' * 32
            first = module.chunks(item, nonce)
            initial = await anext(first)
            self.assertIn('CMSR_FAILED_' if mode == 'transport' else '<code></code>', initial)
            next_chunk = asyncio.create_task(anext(first))
            await asyncio.sleep(0)
            self.assertEqual(item.paused, 'failed')
            self.assertFalse(next_chunk.done())
            item.fail_release.set()
            if mode == 'transport':
                with self.assertRaises(ConnectionResetError):
                    await next_chunk
            else:
                self.assertIn('stop', await next_chunk)
                await first.aclose()
            second = module.chunks(item, nonce)
            self.assertIn('CMSR_OK_', await anext(second))
            tail = asyncio.create_task(anext(second))
            await asyncio.sleep(0)
            self.assertEqual(item.paused, 'success')
            self.assertFalse(item.completed)
            self.assertFalse(tail.done())
            item.success_release.set()
            self.assertIn('CMSR_FINAL_', await tail)
            rest = [chunk async for chunk in second]
            self.assertTrue(item.completed)
            self.assertEqual(item.calls, 2)
            self.assertIn('[DONE]', rest[-1])
            with self.assertRaises(RuntimeError):
                await anext(module.chunks(item, nonce))

    def test_control_rejects_nonlocal_request(self):
        from types import SimpleNamespace
        request = SimpleNamespace(client=SimpleNamespace(host='192.0.2.1'))
        with self.assertRaises(module.HTTPException) as caught:
            module.controlled(request)
        self.assertEqual(caught.exception.status_code, 403)

    def test_unknown_scenario_is_not_generic_success(self):
        with self.assertRaises(module.HTTPException) as caught:
            module.lookup('b' * 32)
        self.assertEqual(caught.exception.status_code, 404)
