from __future__ import annotations

import asyncio
import logging

import pytest

from services import agent_repository_service as service


AGENT_ID = 101
OTHER_AGENT_ID = 202
NO_ROWS_AGENT_ID = 999
TENANT_ID = 'tenant-a'
USER_ID = 'user-1'


def _summary_record(agent_id, *, downloads):
    return {
        'agent_repository_id': 9000 + agent_id,
        'agent_id': agent_id,
        'author': 'author',
        'submitted_by': 'publisher@example.com',
        'name': f'name-{agent_id}',
        'display_name': f'Display {agent_id}',
        'description': 'desc',
        'status': 'shared',
        'tags': ['tag'],
        'tool_count': 1,
        'version_name': 'V1',
        'icon': 'icon',
        'downloads': downloads,
        'content': '',
    }


def _detail_record(agent_id, *, downloads):
    record = _summary_record(agent_id, downloads=downloads)
    record['create_time'] = None
    record['agent_info_json'] = None
    return record


def _agent_dict(agent_id):
    return {
        'agent_id': agent_id,
        'name': f'name-{agent_id}',
        'display_name': f'Display {agent_id}',
        'description': 'desc',
        'permission': 'EDIT',
    }


@pytest.mark.case_id('UT-BE-AUTO-3BBF7896AFA3ABF2')
@pytest.mark.stage('D1')
def test_agent_repository_downloads_sum_across_rows(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    state = {
        'totals': {AGENT_ID: 8, OTHER_AGENT_ID: 7},
        'summaries': [],
        'agents': [],
        'detail_record': None,
    }

    def fake_sum_downloads(agent_ids):
        totals = state['totals']
        return {int(aid): totals[int(aid)] for aid in agent_ids if int(aid) in totals}

    def fake_list_summaries(publisher_tenant_id, *, status=None, agent_id=None):
        return list(state['summaries'])

    def fake_get_by_id(repository_id, publisher_tenant_id):
        return state['detail_record']

    async def fake_list_all_agent_info(tenant_id, user_id):
        return list(state['agents'])

    def fake_fetch_mine_metadata(tenant_id, agent_ids):
        return {int(aid): {'created_by': USER_ID} for aid in agent_ids}

    def fake_list_by_agent_ids(agent_ids, *, statuses, publisher_tenant_id):
        return []

    monkeypatch.setattr(
        service, 'sum_agent_repository_downloads_by_agent_ids', fake_sum_downloads
    )
    monkeypatch.setattr(service, 'list_agent_repository_summaries', fake_list_summaries)
    monkeypatch.setattr(service, 'get_agent_repository_by_id', fake_get_by_id)
    monkeypatch.setattr(service, 'list_all_agent_info_impl', fake_list_all_agent_info)
    monkeypatch.setattr(service, 'fetch_draft_agent_mine_metadata', fake_fetch_mine_metadata)
    monkeypatch.setattr(service, 'list_agent_repository_by_agent_ids', fake_list_by_agent_ids)
    monkeypatch.setattr(
        service.TagManagementDB,
        'list_resource_assignment_display_values_by_ids',
        staticmethod(lambda *args, **kwargs: {}),
    )

    state['summaries'] = [
        _summary_record(AGENT_ID, downloads=3),
        _summary_record(OTHER_AGENT_ID, downloads=7),
    ]
    state['detail_record'] = _detail_record(AGENT_ID, downloads=3)
    state['agents'] = [_agent_dict(AGENT_ID), _agent_dict(OTHER_AGENT_ID)]

    listing = service.list_agent_repository_listings_impl(TENANT_ID, page=1, page_size=10)
    listing_by_id = {item['agent_id']: item for item in listing['items']}
    assert listing_by_id[AGENT_ID]['downloads'] == 8
    assert listing_by_id[AGENT_ID]['downloads'] != 3
    assert listing_by_id[OTHER_AGENT_ID]['downloads'] == 7

    mine = asyncio.run(
        service.list_my_editable_agents_impl(TENANT_ID, USER_ID, page=1, page_size=10)
    )
    mine_by_id = {item['agent_id']: item for item in mine['items']}
    assert mine_by_id[AGENT_ID]['downloads'] == 8
    assert mine_by_id[OTHER_AGENT_ID]['downloads'] == 7

    detail = service.get_agent_repository_listing_detail_impl(9000 + AGENT_ID, TENANT_ID)
    assert detail['agent_id'] == AGENT_ID
    assert detail['downloads'] == 8
    assert detail['downloads'] != 3

    state['totals'] = {}
    state['summaries'] = [_summary_record(NO_ROWS_AGENT_ID, downloads=None)]
    state['detail_record'] = _detail_record(NO_ROWS_AGENT_ID, downloads=None)
    state['agents'] = [_agent_dict(NO_ROWS_AGENT_ID)]

    assert service._get_agent_download_totals([NO_ROWS_AGENT_ID]) == {}

    listing_empty = service.list_agent_repository_listings_impl(TENANT_ID, page=1, page_size=10)
    empty_item = listing_empty['items'][0]
    assert empty_item['downloads'] == 0
    assert empty_item['downloads'] is not None

    mine_empty = asyncio.run(
        service.list_my_editable_agents_impl(TENANT_ID, USER_ID, page=1, page_size=10)
    )
    assert mine_empty['items'][0]['downloads'] == 0
    assert mine_empty['items'][0]['downloads'] is not None

    detail_empty = service.get_agent_repository_listing_detail_impl(
        9000 + NO_ROWS_AGENT_ID, TENANT_ID
    )
    assert detail_empty['downloads'] == 0
    assert detail_empty['downloads'] is not None

    secret_markers = ('api_key', 'apikey', 'access_key', 'secret', 'password', 'token', 'bearer')
    leaked = [
        record.getMessage()
        for record in caplog.records
        if any(marker in record.getMessage().lower() for marker in secret_markers)
    ]
    assert not leaked, leaked
