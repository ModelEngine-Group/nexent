"""Check fault injection and negative detection without product mutations."""
import asyncio
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


provider = load('prompt_fault_test', 'test-e2e/infra/environment/services/test-assets/prompt_fault_provider.py')
case = load('prompt_fault_case_test', 'test-e2e/cases/AGT-012/test.py')
revision = load('local_revision_prerequisite_test', 'test-e2e/cases/AGT-AUTO-6A6BC7594487E771/test.py')


class PromptFaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_variant_failure_stays_red_and_does_not_omit_second_fault(self):
        with patch.object(case, 'exercise_provider_fault',
                          new=AsyncMock(side_effect=[AssertionError('recovery failed'), None])) as exercise:
            with self.assertRaisesRegex(AssertionError, 'unavailable: recovery failed'):
                await case.test_prompt_provider_failure_preserves_draft('fixture')
        self.assertEqual([call.args[1] for call in exercise.call_args_list], ['unavailable', 'timeout'])

    async def test_readback_after_fault_does_not_reuse_closed_keepalive(self):
        clients = []
        draft = {'agent_id': 123, 'duty_prompt': 'unchanged'}

        @asynccontextmanager
        async def fake_model(*args):
            yield 456, 'fixture'

        @asynccontextmanager
        async def fake_agent(*args, **kwargs):
            yield 123, {}

        class API:
            def __init__(self):
                self.failed = False

            async def post(self, path, json):
                if self.failed:
                    raise httpx.RemoteProtocolError('Closed after application error')
                status, body, headers = 200, draft, {}
                if path == '/prompt/optimize/from_debug':
                    if json['model_id'] == 456:
                        self.failed = True
                        status, body = 500, {'message': 'Internal server error, please try again later.'}
                    else:
                        body = {'data': {'optimized_full_prompt': 'healthy suggestion'}}
                        headers = {'X-Prompt-Source': 'jiuwen'}
                return httpx.Response(status, json=body, headers=headers,
                                      request=httpx.Request('POST', 'http://fixture' + path))

        @asynccontextmanager
        async def fake_client(*args, **kwargs):
            api = API()
            clients.append(api)
            yield api

        with patch.object(case, 'fault_model', fake_model), \
                patch.object(case, '_draft_agent', fake_agent), \
                patch.object(case, 'client', fake_client), \
                patch.object(case, '_llm_id', new=AsyncMock(return_value=789)), \
                patch.object(case, 'fault_control', new=AsyncMock(return_value={'mode': 'unavailable', 'calls': 1})), \
                patch.object(case, 'write_case_evidence'):
            await case.exercise_provider_fault(SimpleNamespace(access_token='fixture'), 'unavailable')
        self.assertEqual(len(clients), 3)
        self.assertTrue(clients[0].failed)

    async def test_scoped_failure_receipts_timeout_and_cleanup(self):
        app = FastAPI()
        app.include_router(provider.router)
        nonce = uuid4().hex
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 1))
        async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as api:
            response = await api.post(f'/prompt-fault/{nonce}/reset', json={'mode': 'timeout'})
            self.assertEqual(response.status_code, 200)
            with patch.object(provider.asyncio, 'sleep', return_value=None) as sleep:
                response = await api.post(f'/prompt-fault/{nonce}/v1/chat/completions',
                                          json={'api_key': 'must-not-be-recorded', 'messages': []})
                sleep.assert_awaited_once_with(3)
            self.assertEqual(response.status_code, 503)
            receipt = (await api.get(f'/prompt-fault/{nonce}/state')).json()
            self.assertEqual(receipt, {'mode': 'timeout', 'calls': 1})
            await api.delete(f'/prompt-fault/{nonce}')
            self.assertEqual((await api.get(f'/prompt-fault/{nonce}/state')).status_code, 404)

    async def test_control_is_not_remotely_mutable(self):
        app = FastAPI()
        app.include_router(provider.router)
        transport = httpx.ASGITransport(app=app, client=('192.0.2.1', 1))
        async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as api:
            self.assertEqual((await api.post(f'/prompt-fault/{uuid4().hex}/reset',
                                            json={'mode': 'unavailable'})).status_code, 403)

    def test_rejection_requires_wire_no_mutation_exact_error_and_bounded_time(self):
        failure = httpx.Response(500, json={'message': 'Internal server error, please try again later.'},
                                 request=httpx.Request('POST', 'http://fixture'))
        receipt = {'mode': 'unavailable', 'calls': 1}
        before = {'duty_prompt': 'original'}
        case.assert_fault(failure, receipt, before, dict(before), 2, 'unavailable')
        for args in [
            (failure, {**receipt, 'calls': 0}, before, before, 2, 'unavailable'),
            (failure, receipt, before, {'duty_prompt': 'changed'}, 2, 'unavailable'),
            (httpx.Response(200, json={'data': {}}, request=httpx.Request('POST', 'http://fixture')),
             receipt, before, before, 2, 'unavailable'),
            (failure, receipt, before, before, 91, 'unavailable'),
        ]:
            with self.assertRaises(AssertionError):
                case.assert_fault(*args)

    def test_complete_draft_requires_saved_fields_not_a_completion_marker(self):
        before = {'name': 'owned_draft', 'description': 'complete', 'duty_prompt': 'do the task',
                  'greeting_message': 'hello', 'example_questions': ['a question'],
                  'tools': [], 'skills': [], 'related_agent_ids': []}
        revision.assert_complete_draft(before)
        for field in ('name', 'description', 'duty_prompt', 'greeting_message', 'example_questions'):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                revision.assert_complete_draft({**before, field: ''})
        with self.assertRaises(AssertionError):
            revision.assert_complete_draft({**before, 'tools': [{'tool_id': 1}]})

    def test_snapshot_uses_actual_agent_payload_and_rejects_empty_readback(self):
        draft = {'agent_id': 123, 'duty_prompt': 'original'}
        self.assertEqual(case.snapshot(draft), case.snapshot({'data': draft}))
        self.assertNotEqual(case.snapshot(draft), case.snapshot({**draft, 'duty_prompt': 'changed'}))
        with self.assertRaises(AssertionError):
            case.snapshot({'message': 'not an Agent'})
