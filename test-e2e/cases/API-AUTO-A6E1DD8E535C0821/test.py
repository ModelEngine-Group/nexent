import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from consts.model import MessageRequest, MessageUnit
from database.client import get_db_session
from services.conversation_management_service import save_message, save_source_search
from shared.http import assert_status, client
from shared.asset_registry import register_asset

SCORE = Decimal('12.345678')


def _run_id():
    return (
        os.environ.get('NEXENT_RUN_ID')
        or os.environ.get('TEST_BATCH')
        or uuid.uuid4().hex[:8]
    )


def _to_decimal(value):
    if value is None:
        raise AssertionError('expected a non-null score value')
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value).strip())


@pytest.mark.asyncio
@pytest.mark.case_id('API-AUTO-A6E1DD8E535C0821')
@pytest.mark.stage('D3')
async def test_score_overall_precision_roundtrip(tenant_a_user):
    identity = tenant_a_user
    run_id = _run_id()
    conversation_id = None
    try:
        with get_db_session() as session:
            col = session.execute(
                text(
                    'SELECT data_type, numeric_precision, numeric_scale '
                    'FROM information_schema.columns '
                    'WHERE table_schema = :schema '
                    'AND table_name = :table AND column_name = :column'
                ),
                {
                    'schema': 'nexent',
                    'table': 'conversation_source_search_t',
                    'column': 'score_overall',
                },
            ).fetchone()
        assert col is not None, 'score_overall column missing from conversation_source_search_t'
        assert str(col.data_type).lower() in ('numeric', 'decimal'), col
        assert int(col.numeric_precision) == 14, col
        assert int(col.numeric_scale) == 6, col

        async with client('runtime', token=identity.access_token) as api:
            create_resp = await api.put(
                '/conversation/create', json={'title': f'score-overall-{run_id}'}
            )
            assert_status(create_resp, 200)
            create_body = create_resp.json()
            assert create_body.get('code') == 0, create_body
            conversation_id = int(create_body['data']['conversation_id'])
            register_asset('owned_conversations', str(conversation_id), conversation_id,
                           owner_case_id='API-AUTO-A6E1DD8E535C0821', cleanup={
                               'service': 'runtime', 'identity': identity.id,
                               'method': 'DELETE', 'path': f'/conversation/{conversation_id}',
                               'allowed_statuses': [200, 404],
                           })

        message_id = save_message(
            MessageRequest(
                conversation_id=conversation_id,
                message_idx=0,
                role='user',
                message=[MessageUnit(type='string', content=f'accurate-search-{run_id}')],
            ),
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            status='completed',
        )
        assert message_id is not None and int(message_id) > 0

        search_id = save_source_search(
            {
                'message_id': message_id,
                'conversation_id': conversation_id,
                'source_type': 'web',
                'source_title': f'accurate-source-{run_id}',
                'source_location': 'https://example.com/',
                'source_content': 'source content for score_overall precision verification',
                'cite_index': 0,
                'search_type': 'accurate_search',
                'tool_sign': 'es_accurate',
                'score_overall': SCORE,
            },
            user_id=identity.user_id,
        )
        assert search_id is not None and int(search_id) > 0

        async with client('runtime', token=identity.access_token) as api:
            sources_resp = await api.post(
                '/conversation/sources',
                json={'conversation_id': conversation_id, 'type': 'search'},
            )
            assert_status(sources_resp, 200)
            sources_body = sources_resp.json()
        assert sources_body.get('code') == 0, sources_body
        searches = (sources_body.get('data') or {}).get('searches') or []
        matching = [s for s in searches if s.get('message_id') == message_id]
        assert matching, f'search record message_id={message_id} not found'
        api_score = matching[0].get('score')
        assert _to_decimal(api_score) == SCORE, f'API score {api_score!r} != 12.345678'

        with get_db_session() as session:
            db_row = session.execute(
                text(
                    'SELECT score_overall FROM nexent.conversation_source_search_t '
                    'WHERE search_id = :search_id AND delete_flag = :flag'
                ),
                {'search_id': search_id, 'flag': 'N'},
            ).fetchone()
        assert db_row is not None, 'persisted search record not found'
        db_score = db_row[0]
        assert _to_decimal(db_score) == SCORE, f'DB score_overall {db_score!r} != 12.345678'
    finally:
        if conversation_id is not None:
            try:
                async with client('runtime', token=identity.access_token) as api:
                    await api.delete(f'/conversation/{conversation_id}')
            except Exception:
                pass
