# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Monitor compatibility with canonical ModelService usage totals."""
import json
from unittest.mock import Mock

import pytest
from nexent.monitor.monitoring import LLMTokenTracker


@pytest.mark.parametrize("total", [0, 99])
def test_token_tracker_accepts_reported_total(total):
    manager = Mock(is_enabled=True)
    span = Mock()
    tracker = LLMTokenTracker(manager, "fixture", span)
    tracker.record_completion(2, 3, total_tokens=total)
    attrs = span.set_attributes.call_args.args[0]
    assert attrs["llm.token_count.total"] == total
    assert json.loads(attrs["llm.usage_details"])["total"] == total


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("total", [-1, True, "5"])
def test_token_tracker_rejects_invalid_reported_total(total, enabled):
    manager = Mock(is_enabled=enabled)
    span = Mock()
    tracker = LLMTokenTracker(manager, "fixture", span)
    with pytest.raises(ValueError):
        tracker.record_completion(2, 3, total_tokens=total)
    manager.record_llm_metrics.assert_not_called()
    span.set_attributes.assert_not_called()
    assert tracker.input_tokens == tracker.output_tokens == 0


@pytest.mark.parametrize("reported", [None, ...])
def test_token_tracker_distinguishes_unknown_and_omitted_totals(reported):
    manager = Mock(is_enabled=True)
    span = Mock()
    tracker = LLMTokenTracker(manager, "fixture", span)
    if reported is ...:
        tracker.record_completion(2, 3)
    else:
        tracker.record_completion(2, 3, total_tokens=reported)
    attrs = span.set_attributes.call_args.args[0]
    details = json.loads(attrs["llm.usage_details"])
    assert tracker.input_tokens == 2 and tracker.output_tokens == 3
    if reported is None:
        assert "llm.token_count.total" not in attrs and "total" not in details
    else:
        assert attrs["llm.token_count.total"] == details["total"] == 5


def test_disabled_tracker_accepts_valid_total_without_monitoring_side_effects():
    manager = Mock(is_enabled=False)
    span = Mock()
    tracker = LLMTokenTracker(manager, "fixture", span)
    tracker.record_completion(2, 3, total_tokens=0)
    manager.record_llm_metrics.assert_not_called()
    span.set_attributes.assert_not_called()
    assert tracker.input_tokens == tracker.output_tokens == 0
