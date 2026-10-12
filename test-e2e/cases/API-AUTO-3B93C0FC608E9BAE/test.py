from __future__ import annotations

import pytest

from shared.http import assert_status, client


@pytest.mark.asyncio
@pytest.mark.stage('D2')
@pytest.mark.case_id('API-AUTO-3B93C0FC608E9BAE')
async def test_skill_repository_tag_stats_and_mine_counts_contract(
    tenant_a_admin,
    tenant_a_dev,
    tenant_a_user,
):
    async with client('config', token=tenant_a_dev.access_token) as api:
        tags_resp = await api.get('/repository/skill/tags')
        assert_status(tags_resp, 200)
        tags_body = tags_resp.json()
        assert isinstance(tags_body, dict)
        assert 'items' in tags_body
        items = tags_body['items']
        assert isinstance(items, list)
        observed_tags = []
        for item in items:
            assert isinstance(item, dict)
            assert set(item.keys()) == {'tag', 'count'}
            tag = item['tag']
            count = item['count']
            assert isinstance(tag, str) and tag != ''
            assert isinstance(count, int) and count >= 1
            observed_tags.append(tag)
        assert observed_tags == sorted(observed_tags)
        assert len(observed_tags) == len(set(observed_tags))

    async with client('config', token=tenant_a_admin.access_token) as api:
        counts_resp = await api.get('/repository/skill/mine/counts')
        assert_status(counts_resp, 200)
        counts_body = counts_resp.json()
        assert isinstance(counts_body, dict)
        assert 'counts' in counts_body
        counts = counts_body['counts']
        assert isinstance(counts, dict)
        assert set(counts.keys()) == {'all', 'created', 'others'}
        for key in ('all', 'created', 'others'):
            assert isinstance(counts[key], int) and counts[key] >= 0
        assert counts['all'] == counts['created'] + counts['others']

    async with client('config', token=tenant_a_user.access_token) as api:
        forbidden = await api.get('/repository/skill/tags')
        assert_status(forbidden, 403)

    async with client('config') as api:
        missing_tags = await api.get('/repository/skill/tags')
        assert_status(missing_tags, 401)
        missing_counts = await api.get('/repository/skill/mine/counts')
        assert_status(missing_counts, 401)

    async with client('config', token='invalid-token-value') as api:
        invalid_tags = await api.get('/repository/skill/tags')
        assert_status(invalid_tags, 401)
        assert 'invalid-token-value' not in invalid_tags.text
        invalid_counts = await api.get('/repository/skill/mine/counts')
        assert_status(invalid_counts, 401)
        assert 'invalid-token-value' not in invalid_counts.text
