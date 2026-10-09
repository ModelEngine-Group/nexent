"""Real Agent/observer/SSE/persistence, with only the provider controlled."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from shared.auth import sign_in
from shared.cmsr import control, setup, verify_history, wait_paused
from shared.factories.conversation import owned_conversation
from shared.http import client, assert_status, MODEL_TIMEOUT

pytestmark = [pytest.mark.case_id('CMSR-D3-001'), pytest.mark.stage('D3')]


@pytest.mark.asyncio
async def test_cmsr_d3_001():
    identity = await sign_in('tenant_a_admin')
    for mode in ('transport', 'semantic'):
        fixture = await setup('CMSR-D3-001')
        nonce = fixture['nonce']
        await control(nonce, 'reset', mode=mode)
        try:
            async with owned_conversation(identity, 'CMSR ' + nonce) as conversation_id:
                events = []

                async def consume():
                    async with client('runtime', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                        async with api.stream('POST', '/agent/run', json={
                            'query': 'Execute one code action and finish.', 'agent_id': fixture['agent_id'],
                            'conversation_id': conversation_id, 'history': [], 'is_debug': False}) as response:
                            assert_status(response, 200)
                            async for line in response.aiter_lines():
                                if line.startswith('data:') and line[5:].strip() != '[DONE]':
                                    events.append(json.loads(line[5:]))

                task = asyncio.create_task(consume())
                try:
                    await wait_paused(nonce, 'failed')
                    async with asyncio.timeout(15):
                        while not any(e.get('type') == 'model_output_thinking' for e in events):
                            if task.done():
                                await task
                                pytest.fail('Stream completed before first provider fragment')
                            await asyncio.sleep(0.1)
                        step_index = next(i for i, e in enumerate(events) if e.get('type') == 'step_count')
                        begin_index = next(i for i, e in enumerate(events) if e.get('type') == 'model_attempt_control' and e.get('phase') == 'begin')
                        output_index = next(i for i, e in enumerate(events) if e.get('type') == 'model_output_thinking')
                        assert step_index < begin_index < output_index
                    await control(nonce, 'failed')
                    await wait_paused(nonce, 'success')
                    async with asyncio.timeout(15):
                        while not any('CMSR_OK_' + nonce in str(e.get('content', '')) for e in events):
                            if task.done():
                                await task
                                pytest.fail('Stream finished without live successful fragment')
                            await asyncio.sleep(0.1)
                    state = await control(nonce, 'state')
                    assert state['calls'] == 2 and not state['completed']
                    assert sum(e.get('phase') == 'rollback' for e in events) == 1
                    assert sum(e.get('type') == 'step_count' for e in events) == 1
                    await control(nonce, 'success')
                    await asyncio.wait_for(task, 60)
                    assert sum(e.get('phase') == 'commit' for e in events) == 1
                    assert sum(e.get('type') == 'parse' for e in events) == 1
                    assert (await control(nonce, 'state'))['calls'] == 2
                    async with client('runtime', token=identity.access_token) as api:
                        history = await api.get(f'/conversation/{conversation_id}')
                    assert_status(history, 200)
                    verify_history(history.json(), nonce)
                finally:
                    if os.getenv('RESULT_DIR'):
                        Path(os.environ['RESULT_DIR'], 'cmsr-' + mode + '-events.json').write_text(
                            json.dumps([{'type': e.get('type'), 'phase': e.get('phase'),
                                'has_success_marker': 'CMSR_OK_' + nonce in str(e.get('content', ''))}
                                for e in events], indent=2), encoding='utf-8')
                    await control(nonce, 'failed')
                    await control(nonce, 'success')
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            await control(nonce, 'delete')
