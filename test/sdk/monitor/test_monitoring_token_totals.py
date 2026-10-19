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


@pytest.mark.parametrize("total", [-1, True, "5"])
def test_token_tracker_rejects_invalid_reported_total(total):
    manager = Mock(is_enabled=True)
    tracker = LLMTokenTracker(manager, "fixture", Mock())
    with pytest.raises(ValueError):
        tracker.record_completion(2, 3, total_tokens=total)
    manager.record_llm_metrics.assert_not_called()
