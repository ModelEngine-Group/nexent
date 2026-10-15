from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from consts.model import HybridSearchRequest

EXPECTED_FIELDS = {'query', 'index_names', 'top_k', 'weight_accurate', 'tag_predicates'}


@pytest.mark.case_id('UT-BE-AUTO-39A8846CFEA5224E')
@pytest.mark.stage('D1')
def test_hybrid_search_request_tag_predicates_contract():
    minimal = HybridSearchRequest(query='hello', index_names=['kb1'])
    assert minimal.tag_predicates == []
    assert minimal.top_k == 10
    assert minimal.weight_accurate is None

    dumped = minimal.model_dump()
    assert set(dumped.keys()) == EXPECTED_FIELDS
    assert dumped['tag_predicates'] == []
    assert json.loads(minimal.model_dump_json())['tag_predicates'] == []

    single_group = [{'definition_id': 'urn:def:color', 'value_ids': ['red']}]
    or_within = [{'definition_id': 'urn:def:color', 'value_ids': ['red', 'blue']}]
    and_across = [
        {'definition_id': 'urn:def:color', 'value_ids': ['red', 'blue']},
        {'definition_id': 'urn:def:size', 'value_ids': ['large']},
    ]
    for groups in (single_group, or_within, and_across):
        req = HybridSearchRequest(
            query='hello', index_names=['kb1'], tag_predicates=groups
        )
        assert req.model_dump()['tag_predicates'] == groups
        assert json.loads(req.model_dump_json())['tag_predicates'] == groups

        rebuilt = HybridSearchRequest.model_validate(req.model_dump())
        assert rebuilt.tag_predicates == groups
        assert rebuilt.model_dump() == req.model_dump()

        rebuilt_json = HybridSearchRequest.model_validate_json(req.model_dump_json())
        assert rebuilt_json.tag_predicates == groups
        assert rebuilt_json.model_dump() == req.model_dump()

    empty_groups = HybridSearchRequest(query='hello', index_names=['kb1'], tag_predicates=[])
    assert empty_groups.tag_predicates == []
    empty_value_ids = HybridSearchRequest(
        query='hello',
        index_names=['kb1'],
        tag_predicates=[{'definition_id': 'urn:def:color', 'value_ids': []}],
    )
    assert empty_value_ids.model_dump()['tag_predicates'] == [
        {'definition_id': 'urn:def:color', 'value_ids': []}
    ]

    with pytest.raises(ValidationError):
        HybridSearchRequest(query='', index_names=['kb1'])
    with pytest.raises(ValidationError):
        HybridSearchRequest(query='hello', index_names=[])
    for bad_top_k in (0, 101):
        with pytest.raises(ValidationError):
            HybridSearchRequest(query='hello', index_names=['kb1'], top_k=bad_top_k)
    for bad_weight in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            HybridSearchRequest(query='hello', index_names=['kb1'], weight_accurate=bad_weight)

    assert HybridSearchRequest(query='hello', index_names=['kb1'], top_k=1).top_k == 1
    assert HybridSearchRequest(query='hello', index_names=['kb1'], top_k=100).top_k == 100
    assert HybridSearchRequest(query='hello', index_names=['kb1'], weight_accurate=0.0).weight_accurate == 0.0
    assert HybridSearchRequest(query='hello', index_names=['kb1'], weight_accurate=1.0).weight_accurate == 1.0
