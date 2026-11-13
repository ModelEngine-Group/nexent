# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Provider-reported totals remain distinct from historical inferred totals."""

import json
from unittest.mock import Mock

import pytest
from nexent.monitor.monitoring import LLMTokenTracker


@pytest.mark.parametrize('total', [None, 0, 7])
def test_explicit_provider_total_does_not_infer_or_replace_missing_values(total):
    manager, span = Mock(), Mock()
    manager.is_enabled = True
    tracker = LLMTokenTracker(manager, 'controlled', span)
    tracker.record_completion(10, 0, total_tokens=total)
    attributes = span.set_attributes.call_args.args[0]
    details = json.loads(attributes['llm.usage_details'])
    assert attributes['llm.token_count.prompt'] == 10
    assert attributes['llm.token_count.completion'] == 0
    if total is None:
        assert 'llm.token_count.total' not in attributes and 'total' not in details
    else:
        assert attributes['llm.token_count.total'] == details['total'] == total


def test_existing_callers_keep_their_total_count_contract():
    manager, span = Mock(), Mock()
    manager.is_enabled = True
    LLMTokenTracker(manager, 'controlled', span).record_completion(10, 5)
    assert span.set_attributes.call_args.args[0]['llm.token_count.total'] == 15
