from __future__ import annotations

import pytest

from d3.assets import model_id
from shared.factories.conversation import owned_conversation
from shared.resource_ids import absent_numeric_id
from shared.http import assert_status, client, response_message


CASE_ID = 'API-AUTO-E2709DB42A4A1EA8'
async def _current_title(api, conversation_id: int) -> str:
    response = await api.get(f'/conversation/{conversation_id}')
    assert_status(response, 200)
    items = response.json().get('data') or []
    assert items, f'no conversation history for {conversation_id}'
    return items[0]['conversation_title']


def _detail_text(response) -> str:
    return response_message(response)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
@pytest.mark.asyncio
async def test_generate_title_model_id_contract(tenant_a_admin):
    llm_model_id = await model_id('llm', tenant_a_admin)
    non_llm_model_id = await model_id('embedding', tenant_a_admin)
    unavailable_model_id = absent_numeric_id(__name__)
    question = '请帮我总结一下今天的新闻'

    async with owned_conversation(tenant_a_admin, 'generate-title-contract') as conversation_id, \
            client('runtime', token=tenant_a_admin.access_token) as api:
        original_title = await _current_title(api, conversation_id)

        unavailable = await api.post(
            '/conversation/generate_title',
            json={'conversation_id': conversation_id, 'question': question, 'model_id': unavailable_model_id},
        )
        assert unavailable.status_code == 422, (
            f'expected 422 for nonexistent model, got {unavailable.status_code}: {unavailable.text}'
        )
        assert 'Selected model is unavailable' in _detail_text(unavailable)
        assert await _current_title(api, conversation_id) == original_title

        non_llm = await api.post(
            '/conversation/generate_title',
            json={'conversation_id': conversation_id, 'question': question, 'model_id': non_llm_model_id},
        )
        assert non_llm.status_code == 422, (
            f'expected 422 for non-llm model, got {non_llm.status_code}: {non_llm.text}'
        )
        assert 'Selected model is not an LLM model' in _detail_text(non_llm)
        assert await _current_title(api, conversation_id) == original_title

        ok = await api.post(
            '/conversation/generate_title',
            json={'conversation_id': conversation_id, 'question': question, 'model_id': llm_model_id},
        )
        assert_status(ok, 200)
        ok_body = ok.json()
        assert ok_body['code'] == 0
        assert ok_body['message'] == 'success'
        assert isinstance(ok_body['data'], str) and ok_body['data'].strip()
        assert await _current_title(api, conversation_id) == ok_body['data']

        fallback = await api.post(
            '/conversation/generate_title',
            json={'conversation_id': conversation_id, 'question': question},
        )
        assert_status(fallback, 200)
        fallback_body = fallback.json()
        assert fallback_body['code'] == 0
        assert fallback_body['message'] == 'success'
        assert isinstance(fallback_body['data'], str) and fallback_body['data'].strip()
