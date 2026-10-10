from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import json
import math

import pytest

from shared.http import assert_status, client, response_message

CASE_ID = 'API-AUTO-D6C1BBC6199D63C0'
JSON_ERROR = 'tag_predicates must be valid JSON'
LIST_ERROR = 'tag_predicates must be a list'


def _assert_detail(resp, status, detail):
    assert_status(resp, status)
    assert response_message(resp) == detail, f'error message mismatch: {resp.json()!r}'


def _enc(predicates):
    return json.dumps(predicates, separators=(',', ':'))


async def _all(api, path, **params):
    out = []
    page = 1
    while True:
        resp = await api.get(path, params={'page': page, 'page_size': 100, **params})
        assert_status(resp, 200)
        payload = resp.json()
        items = payload.get('items') or []
        out.extend(items)
        total = int((payload.get('pagination') or {}).get('total') or 0)
        if not items or len(out) >= total:
            return out
        page += 1


async def _shared(api):
    return await _all(api, '/repository/agent', status='shared')


async def _assignments(api, agent_id):
    resp = await api.get(f'/tag-libraries/assignments/agent/{agent_id}')
    assert_status(resp, 200)
    return resp.json().get('assignments') or []


def _matches_all(assignments, predicates):
    pairs = {(a.get('definition_id'), a.get('value_id')) for a in assignments}
    for p in predicates:
        vids = set(p['value_ids'])
        if not any(v in vids for (d, v) in pairs if d == p['definition_id']):
            return False
    return True


def _matches_any(assignments, predicates):
    pairs = {(a.get('definition_id'), a.get('value_id')) for a in assignments}
    for p in predicates:
        vids = set(p['value_ids'])
        if any(v in vids for (d, v) in pairs if d == p['definition_id']):
            return True
    return False


def _matches_text(item, search):
    q = (search or '').strip().lower()
    if not q:
        return True
    name = str(item.get('display_name') or item.get('name') or '').lower()
    desc = str(item.get('description') or '').lower()
    tags = item.get('tags') or []
    tag_text = ' '.join(str(t).lower() for t in tags if isinstance(t, str))
    return q in name or q in desc or q in tag_text


@pytest.mark.stage('D2')
@pytest.mark.case_id(CASE_ID)
@pytest.mark.asyncio
async def test_api_auto_d6c1bbc6199d63c0(tenant_a_admin, tenant_a_user, tenant_b_admin, tenant_b_user):
    async with client('config', token=tenant_a_user.access_token) as api:
        resp = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 10})
        assert_status(resp, 200)
        payload = resp.json()
        assert isinstance(payload.get('items'), list)
        pagination = payload.get('pagination') or {}
        for key in ('page', 'page_size', 'total', 'total_pages'):
            assert key in pagination, f'missing pagination key {key}'
        total = int(pagination['total'])
        page_size = int(pagination['page_size'])
        assert pagination['total_pages'] == (math.ceil(total / page_size) if total else 0)
        for item in payload['items']:
            assert 'agent_repository_id' in item and 'agent_id' in item
            assert isinstance(item.get('tags'), list)

        for param in ('tag_predicates', 'search_tag_predicates'):
            _assert_detail(await api.get('/repository/agent', params={param: 'not-json'}), 400, JSON_ERROR)
            _assert_detail(await api.get('/repository/agent', params={param: json.dumps({'a': 1})}), 400, LIST_ERROR)
            _assert_detail(await api.get('/repository/agent/mine', params={param: 'not-json'}), 400, JSON_ERROR)
            _assert_detail(await api.get('/repository/agent/mine', params={param: json.dumps({'a': 1})}), 400, LIST_ERROR)

    async with client('config') as anon:
        assert_status(await anon.get('/repository/agent'), 401)
        assert_status(await anon.get('/repository/agent/mine'), 401)

    async with client('config', token='invalid-token-value') as api:
        assert_status(await api.get('/repository/agent'), 401)
        assert_status(await api.get('/repository/agent/mine'), 401)

    async with client('config', token=tenant_a_user.access_token) as api:
        shared = await _shared(api)
    agent_ids = [int(i['agent_id']) for i in shared if i.get('agent_id') is not None]

    async with client('config', token=tenant_a_admin.access_token) as admin:
        libs = await admin.get('/tag-libraries')
        assert_status(libs, 200)
        bucket = next((lib for lib in libs.json() if lib.get('bucket_key') == 'default_resource'), None)
        if bucket is not None:
            bucket_id = bucket['bucket_id']
            defs = await admin.get(f'/tag-libraries/{bucket_id}/definitions')
            assert_status(defs, 200)
        assignments_by_agent = {}
        for aid in agent_ids:
            assignments_by_agent[aid] = await _assignments(admin, aid)

    usage = {}
    for assignments in assignments_by_agent.values():
        for a in assignments:
            if a.get('definition_id') is not None and a.get('value_id') is not None:
                usage.setdefault(a['definition_id'], set()).add(a['value_id'])
    predicates = [{'definition_id': d, 'value_ids': sorted(v)} for d, v in sorted(usage.items())]
    predicates = predicates or [{'definition_id': absent_numeric_id(__name__), 'value_ids': [absent_numeric_id(__name__)]}]
    real = [p for p in predicates if p['definition_id'] != absent_numeric_id(__name__)]

    async with client('config', token=tenant_a_user.access_token) as api:
        resp = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 100, 'tag_predicates': _enc(predicates)})
        assert_status(resp, 200)
        got = {int(i['agent_id']) for i in (resp.json().get('items') or []) if i.get('agent_id') is not None}
        expected = {aid for aid in agent_ids if _matches_all(assignments_by_agent[aid], real)} if real else set()
        assert got == expected

        if shared and real:
            head = shared[0]
            choices = [str(head.get('name') or ''), str(head.get('display_name') or ''), str(head.get('description') or '')]
            choices += [str(t) for t in (head.get('tags') or []) if isinstance(t, str)]
            search = next((c for c in choices if c.strip()), '')
            resp = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 100, 'search': search, 'search_tag_predicates': _enc(real)})
            assert_status(resp, 200)
            got = {int(i['agent_id']) for i in (resp.json().get('items') or []) if i.get('agent_id') is not None}
            by_id = {int(i['agent_id']): i for i in shared if i.get('agent_id') is not None}
            expected = {aid for aid, item in by_id.items() if _matches_text(item, search) or _matches_any(assignments_by_agent[aid], real)}
            assert got == expected

        flat = {}
        for item in shared:
            if item.get('agent_id') is None or int(item['agent_id']) in flat:
                continue
            flat[int(item['agent_id'])] = item.get('tags') or []
        by_tag = {}
        for aid, tags in flat.items():
            for t in tags:
                if isinstance(t, str):
                    by_tag.setdefault(t, set()).add(aid)
        target = next(iter(by_tag), '') if by_tag else ''
        if target:
            resp = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 100, 'tag': target})
            assert_status(resp, 200)
            got = {int(i['agent_id']) for i in (resp.json().get('items') or []) if i.get('agent_id') is not None}
            assert got == by_tag[target]
            if len(target) > 1:
                sub = target[:-1]
                resp = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 100, 'tag': sub})
                assert_status(resp, 200)
                got = {int(i['agent_id']) for i in (resp.json().get('items') or []) if i.get('agent_id') is not None}
                assert got == by_tag.get(sub, set())
            variant = target.lower() if target != target.lower() else target.upper()
            if variant != target:
                resp = await api.get('/repository/agent', params={'status': 'shared', 'page': 1, 'page_size': 100, 'tag': variant})
                assert_status(resp, 200)
                got = {int(i['agent_id']) for i in (resp.json().get('items') or []) if i.get('agent_id') is not None}
                assert got == by_tag.get(variant, set())

        resp = await api.get('/repository/agent/mine', params={'new_agent_padding': 'true', 'tag_predicates': _enc(predicates), 'page': 1, 'page_size': 100})
        assert_status(resp, 200)
        mine_items = resp.json().get('items') or []
        for item in mine_items:
            assert not (isinstance(item, dict) and item.get('new_agent_padding') is True)
            aid = item.get('agent_id')
            if aid is not None and real and aid in assignments_by_agent:
                assert _matches_all(assignments_by_agent[aid], real)

    async with client('config', token=tenant_b_admin.access_token) as api_b:
        b_shared = await _shared(api_b)
        b_ids = {int(i['agent_repository_id']) for i in b_shared if i.get('agent_repository_id') is not None}
        async with client('config', token=tenant_a_admin.access_token) as api_a:
            a_shared = await _shared(api_a)
            a_ids = {int(i['agent_repository_id']) for i in a_shared if i.get('agent_repository_id') is not None}
        assert a_ids.isdisjoint(b_ids)
        for listing in a_shared:
            listing_id = listing.get('agent_repository_id')
            if listing_id is not None:
                assert_status(await api_b.get(f'/repository/agent/{listing_id}'), 404)
