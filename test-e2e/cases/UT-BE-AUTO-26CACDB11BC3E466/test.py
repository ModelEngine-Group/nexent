from __future__ import annotations

import asyncio
from unittest import mock

import pytest

import services.agent_repository_service as svc


CASE_ID = 'UT-BE-AUTO-26CACDB11BC3E466'


def _build_agents():
    return [
        ({'agent_id': 1, 'name': 'agent-1'}, {'created_by': 'user-1'}),
        ({'agent_id': 2, 'name': 'agent-2'}, {'created_by': 'user-1'}),
        ({'agent_id': 3, 'name': 'agent-3'}, {'created_by': 'user-2'}),
    ]


def _has_padding(items):
    return any(
        isinstance(item, dict) and item.get('new_agent_padding') is True
        for item in items
    )


def _run_listing(
    *,
    ownership='all',
    search=None,
    tag_predicates=None,
    agent_id=None,
    new_agent_padding=True,
    page=1,
    page_size=10,
):
    agents = [
        {'agent_id': 1, 'name': 'agent-1', 'display_name': 'Agent 1', 'description': 'first', 'permission': 'private'},
        {'agent_id': 2, 'name': 'agent-2', 'display_name': 'Agent 2', 'description': 'second', 'permission': 'private'},
        {'agent_id': 3, 'name': 'agent-3', 'display_name': 'Agent 3', 'description': 'third', 'permission': 'private'},
    ]
    meta_by_id = {
        1: {'created_by': 'user-1', 'current_version_no': 1, 'version_name': 'V1', 'version_create_time': None},
        2: {'created_by': 'user-1', 'current_version_no': 1, 'version_name': 'V1', 'version_create_time': None},
        3: {'created_by': 'user-2', 'current_version_no': 1, 'version_name': 'V1', 'version_create_time': None},
    }
    with (
        mock.patch.object(svc, 'list_all_agent_info_impl', new=mock.AsyncMock(return_value=agents)),
        mock.patch.object(svc, 'fetch_draft_agent_mine_metadata', return_value=meta_by_id),
        mock.patch.object(svc, 'list_agent_repository_by_agent_ids', return_value=[]),
        mock.patch.object(svc, 'sum_agent_repository_downloads_by_agent_ids', return_value={}),
        mock.patch.object(svc.TagManagementDB, 'list_resource_assignment_display_values_by_ids', return_value={}),
        mock.patch.object(svc.TagManagementDB, 'filter_authorized_resource_ids', return_value={'1', '2', '3'}),
    ):
        return asyncio.run(svc.list_my_editable_agents_impl(
            tenant_id='tenant-1',
            user_id='user-1',
            ownership=ownership,
            page=page,
            page_size=page_size,
            search=search,
            new_agent_padding=new_agent_padding,
            agent_id=agent_id,
            tag_predicates=tag_predicates,
        ))


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_mine_agents_padding_pagination_and_include_condition():
    agents = _build_agents()

    paged, total = svc._paginate_mine_agents_with_optional_padding(agents, page=1, page_size=10, include_padding=True)
    assert paged == [{'new_agent_padding': True}, agents[0], agents[1], agents[2]]
    assert total == 4

    paged, total = svc._paginate_mine_agents_with_optional_padding(agents, page=1, page_size=10, include_padding=False)
    assert paged == [agents[0], agents[1], agents[2]]
    assert total == 3

    paged, total = svc._paginate_mine_agents_with_optional_padding(agents, page=2, page_size=2, include_padding=True)
    assert paged == [agents[1], agents[2]]
    assert total == 4

    paged, total = svc._paginate_mine_agents_with_optional_padding([], page=1, page_size=10, include_padding=True)
    assert paged == [{'new_agent_padding': True}]
    assert total == 1

    paged, total = svc._paginate_mine_agents_with_optional_padding([], page=1, page_size=10, include_padding=False)
    assert paged == []
    assert total == 0

    paged, total = svc._paginate_mine_agents_with_optional_padding(agents, page=3, page_size=2, include_padding=True)
    assert paged == []
    assert total == 4

    paged, total = svc._paginate_mine_agents_with_optional_padding(agents, page=2, page_size=2, include_padding=False)
    assert paged == [agents[2]]
    assert total == 3

    result = _run_listing()
    assert result['pagination']['total'] == 4
    assert result['items'][0] == {'new_agent_padding': True}

    result = _run_listing(new_agent_padding=False)
    assert result['pagination']['total'] == 3
    assert not _has_padding(result['items'])

    result = _run_listing(ownership='created')
    assert result['pagination']['total'] == 2
    assert not _has_padding(result['items'])

    result = _run_listing(ownership='others')
    assert result['pagination']['total'] == 1
    assert not _has_padding(result['items'])

    result = _run_listing(search='Agent 1')
    assert result['pagination']['total'] == 1
    assert not _has_padding(result['items'])

    result = _run_listing(tag_predicates=[{'key': 'env'}])
    assert result['pagination']['total'] == 3
    assert not _has_padding(result['items'])

    result = _run_listing(agent_id=2)
    assert result['pagination']['total'] == 1
    assert not _has_padding(result['items'])
