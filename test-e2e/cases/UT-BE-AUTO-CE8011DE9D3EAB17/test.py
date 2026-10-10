from __future__ import annotations

import pytest

from consts.const import PERMISSION_READ
from management.services.knowledge_base.listing import (
    _merge_ordered_info,
    _sort_key,
    apply_read_only_to_asset_indices_info,
    merge_indices_results,
    merge_list_indices_results,
    merge_paginated_list_indices_results,
)


_SECRET_SUBSTRINGS = ('token', 'password', 'secret', 'api_key', 'access_key', 'credential', 'authorization')


def _secret_keys(mapping):
    return [key for key in mapping if any(sub in str(key).lower() for sub in _SECRET_SUBSTRINGS)]


@pytest.mark.case_id('UT-BE-AUTO-CE8011DE9D3EAB17')
@pytest.mark.stage('D1')
def test_knowledge_base_listing_merge_contract():
    assert apply_read_only_to_asset_indices_info({}) == {}

    empty_info = {'indices': ['a'], 'indices_info': []}
    assert apply_read_only_to_asset_indices_info(empty_info) is empty_info
    assert list(empty_info.keys()) == ['indices', 'indices_info']

    asset_full = {
        'indices': ['a1'],
        'indices_info': [
            {'name': 'a1', 'permission': 'EDIT', 'knowledge_id': 'k1'},
            {'name': 'a2', 'permission': 'PRIVATE', 'size': 10},
        ],
    }
    projected = apply_read_only_to_asset_indices_info(asset_full)
    assert projected is not asset_full
    assert projected['indices'] == ['a1']
    assert [info['permission'] for info in projected['indices_info']] == [PERMISSION_READ, PERMISSION_READ]
    assert projected['indices_info'][0]['name'] == 'a1'
    assert projected['indices_info'][0]['knowledge_id'] == 'k1'
    assert projected['indices_info'][1]['size'] == 10
    assert asset_full['indices_info'][0]['permission'] == 'EDIT'
    assert asset_full['indices_info'][1]['permission'] == 'PRIVATE'

    primary = {
        'indices': ['p1', 'p2'],
        'indices_info': [{'name': 'p1'}, {'name': 'p2'}],
    }
    asset = {
        'indices': ['a1'],
        'indices_info': [{'name': 'a1', 'permission': 'EDIT'}],
    }
    merged = merge_indices_results(primary, asset)
    assert merged['indices'] == ['p1', 'p2', 'a1']
    assert merged['count'] == 3
    assert merged['indices_info'] == [
        {'name': 'p1'},
        {'name': 'p2'},
        {'name': 'a1', 'permission': PERMISSION_READ},
    ]
    assert 'total' not in merged
    assert asset['indices_info'][0]['permission'] == 'EDIT'

    primary_page = {
        'indices': ['p1', 'p2'],
        'indices_info': [
            {'name': 'p1', 'update_time': '2024-01-01', 'knowledge_id': '1'},
            {'name': 'p2', 'update_time': '2023-01-01', 'knowledge_id': '2'},
        ],
        'total': 5,
        'facets': {'sources': ['s1'], 'models': ['m1']},
    }
    asset_page = {
        'indices': ['a1', 'a2'],
        'indices_info': [
            {'name': 'a1', 'update_time': '2024-06-01', 'knowledge_id': '3'},
            {'name': 'a2', 'update_time': '2022-01-01', 'knowledge_id': '4'},
        ],
        'total': 3,
        'facets': {'sources': ['s2', 's1'], 'models': ['m2']},
    }

    full_page = merge_indices_results(primary_page, asset_page, offset=0, limit=4)
    assert [info['name'] for info in full_page['indices_info']] == ['a1', 'p1', 'p2', 'a2']
    assert full_page['indices_info'][0]['permission'] == PERMISSION_READ
    assert full_page['indices_info'][3]['permission'] == PERMISSION_READ
    assert full_page['total'] == 8
    assert full_page['indices'] == ['a1', 'p1', 'p2', 'a2']

    page = merge_indices_results(primary_page, asset_page, offset=1, limit=2)
    assert page['indices_info'] == [
        {'name': 'p1', 'update_time': '2024-01-01', 'knowledge_id': '1'},
        {'name': 'p2', 'update_time': '2023-01-01', 'knowledge_id': '2'},
    ]
    assert page['indices'] == ['p1', 'p2']
    assert page['count'] == 2
    assert page['total'] == 8
    assert page['next_offset'] == 3
    assert page['facets'] == {'sources': ['s1', 's2'], 'models': ['m1', 'm2']}

    # The tail fixture contains four materialized rows; its totals must match
    # those rows when checking the final page and terminal next_offset.
    tail = merge_indices_results(
        {**primary_page, 'total': 2}, {**asset_page, 'total': 2}, offset=3, limit=10,
    )
    assert tail['indices'] == ['a2']
    assert tail['next_offset'] is None

    primary_no_total = {'indices': ['x'], 'indices_info': [{'name': 'x'}], 'count': 2}
    asset_no_total = {'indices': ['y'], 'indices_info': [{'name': 'y'}], 'count': 3}
    counted = merge_indices_results(primary_no_total, asset_no_total, offset=0, limit=10)
    assert counted['total'] == 5

    no_info_primary = {'indices': ['p1', 'p2', 'p3'], 'total': 3}
    no_info_asset = {'indices': ['a1', 'a2'], 'total': 2}
    fallback = merge_indices_results(no_info_primary, no_info_asset, offset=1, limit=3)
    assert fallback['indices'] == ['p2', 'p3', 'a1']
    assert fallback['count'] == 3
    assert fallback['total'] == 5
    assert 'indices_info' not in fallback

    assert merge_list_indices_results(primary_page, asset_page) == merge_indices_results(primary_page, asset_page)
    assert merge_paginated_list_indices_results(primary_page, asset_page, 1, 2) == merge_indices_results(primary_page, asset_page, offset=1, limit=2)

    assert _sort_key({'update_time': 't', 'knowledge_id': '5', 'name': 'b'}) == ('t', '00000000000000000005', 'b')
    assert _sort_key({'update_time': None, 'knowledge_id': None, 'name': None}) == ('', '00000000000000000000', '')
    assert _sort_key({}) == ('', '00000000000000000000', '')
    assert _sort_key({'knowledge_id': '10', 'update_time': 't', 'name': 'x'})[1] > _sort_key({'knowledge_id': '2', 'update_time': 't', 'name': 'x'})[1]

    ordered = _merge_ordered_info(
        [
            {'name': 'b', 'update_time': 't', 'knowledge_id': '1'},
            {'name': 'a', 'update_time': 't', 'knowledge_id': '1'},
        ],
        [{'name': 'c', 'update_time': 't', 'knowledge_id': '1'}],
    )
    assert [info['name'] for info in ordered] == ['c', 'b', 'a']

    for result in (merged, full_page, page, tail, counted, fallback):
        assert _secret_keys(result) == []
