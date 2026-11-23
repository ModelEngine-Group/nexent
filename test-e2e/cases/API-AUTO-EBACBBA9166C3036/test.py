from __future__ import annotations

import pytest

from shared.http import assert_status, client, response_message


def _assert_no_secret_fields(value, path=''):
    secret_parts = ('api_key', 'apikey', 'access_key', 'accesskey', 'password', 'secret', 'token')
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower().replace('_', '').replace('-', '')
            assert not any(part in lowered for part in secret_parts), f'unexpected credential field at {path}.{key}'
            _assert_no_secret_fields(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_fields(child, f'{path}[{index}]')


async def _fetch_mine_pages(api, ownership, page_size=30):
    collected = []
    seen = set()
    total = None
    counts = None
    page = 1
    while page <= 10000:
        response = await api.get(
            '/repository/agent/mine',
            params={'ownership': ownership, 'page': page, 'page_size': page_size},
        )
        assert_status(response, 200)
        body = response.json()
        assert isinstance(body, dict)
        for key in ('items', 'counts', 'pagination'):
            assert key in body, f'missing top-level field {key}'
        items = body['items']
        counts = body['counts']
        pagination = body['pagination']
        assert isinstance(items, list)
        assert set(counts.keys()) == {'all', 'created', 'others'}
        for key in ('all', 'created', 'others'):
            assert isinstance(counts[key], int) and counts[key] >= 0, f'counts.{key} must be a non-negative int'
        assert counts['all'] == counts['created'] + counts['others']
        assert set(pagination.keys()) == {'page', 'page_size', 'total', 'total_pages'}
        assert pagination['page'] == page
        assert pagination['page_size'] == page_size
        expected_total_pages = ((pagination['total'] + page_size - 1) // page_size) if pagination['total'] else 0
        assert pagination['total_pages'] == expected_total_pages
        if total is None:
            total = pagination['total']
        for item in items:
            assert isinstance(item, dict)
            agent_id = item.get('agent_id')
            assert agent_id is not None, 'mine item missing agent_id'
            assert agent_id not in seen, f'duplicate agent_id {agent_id} across pages'
            seen.add(agent_id)
            collected.append(agent_id)
        if page >= pagination['total_pages']:
            break
        page += 1
    return collected, counts, total


@pytest.mark.asyncio
@pytest.mark.case_id('API-AUTO-EBACBBA9166C3036')
@pytest.mark.stage('D2')
async def test_agent_mine_ownership_contract(tenant_a_user):
    async with client('config', token=tenant_a_user.access_token) as api:
        all_ids, counts, all_total = await _fetch_mine_pages(api, 'all')
        created_ids, created_counts, created_total = await _fetch_mine_pages(api, 'created')
        others_ids, others_counts, others_total = await _fetch_mine_pages(api, 'others')

        assert counts == created_counts == others_counts
        assert counts['all'] == counts['created'] + counts['others']

        assert all_total == counts['all']
        assert created_total == counts['created']
        assert others_total == counts['others']

        assert len(all_ids) == all_total
        assert len(created_ids) == created_total
        assert len(others_ids) == others_total

        assert set(created_ids).isdisjoint(set(others_ids))
        assert set(all_ids) == set(created_ids) | set(others_ids)

        page_size = 10
        first = await api.get(
            '/repository/agent/mine',
            params={'ownership': 'all', 'page': 1, 'page_size': page_size},
        )
        assert_status(first, 200)
        first_body = first.json()
        first_pagination = first_body['pagination']
        assert first_pagination['page'] == 1
        assert first_pagination['page_size'] == page_size
        assert first_pagination['total'] == counts['all']
        assert first_pagination['total_pages'] == (((counts['all'] + page_size - 1) // page_size) if counts['all'] else 0)
        assert len(first_body['items']) <= page_size
        _assert_no_secret_fields(first_body)

        invalid = await api.get('/repository/agent/mine', params={'ownership': 'unknown'})
        assert invalid.status_code == 400
        detail = response_message(invalid)
        assert 'Invalid ownership filter' in detail
        for allowed in ('all', 'created', 'others'):
            assert allowed in detail

        page_zero = await api.get('/repository/agent/mine', params={'page_size': 0})
        assert page_zero.status_code == 422
        page_huge = await api.get('/repository/agent/mine', params={'page_size': 101})
        assert page_huge.status_code == 422

    async with client('config') as anonymous:
        missing_auth = await anonymous.get('/repository/agent/mine')
        assert missing_auth.status_code == 401
    async with client('config', token='not-a-valid-token') as bad_auth:
        invalid_auth = await bad_auth.get('/repository/agent/mine')
        assert invalid_auth.status_code == 401
