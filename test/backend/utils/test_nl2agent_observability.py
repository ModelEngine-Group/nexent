"""Tests for bounded NL2AGENT metric attributes."""

from utils import nl2agent_observability as observability


class _Counter:
    def __init__(self):
        self.calls = []

    def add(self, value, attributes):
        self.calls.append((value, attributes))


def test_metrics_emit_only_allowlisted_low_cardinality_labels(monkeypatch):
    counters = {
        name: _Counter()
        for name in (
            "_action_total",
            "_cas_conflict_total",
            "_installation_total",
            "_card_parse_total",
            "_atomic_finalize_total",
            "_structured_sse_total",
        )
    }
    for name, counter in counters.items():
        monkeypatch.setattr(observability, name, counter)

    observability.record_action("save_identity", "success")
    observability.record_cas_conflict("message_finalize")
    observability.record_installation("mcp", "lease_takeover")
    observability.record_card_parse("failure")
    observability.record_atomic_finalize("conflict")
    observability.record_structured_sse("sent")

    attributes = [call[1] for counter in counters.values() for call in counter.calls]
    assert attributes == [
        {"action": "save_identity", "outcome": "success"},
        {"operation": "message_finalize"},
        {"resource_type": "mcp", "outcome": "lease_takeover"},
        {"outcome": "failure"},
        {"outcome": "conflict"},
        {"outcome": "sent"},
    ]


def test_untrusted_metric_labels_collapse_to_unknown(monkeypatch):
    counter = _Counter()
    monkeypatch.setattr(observability, "_action_total", counter)

    observability.record_action("secret-token-value", "tenant-123")

    assert counter.calls == [(1, {"action": "unknown", "outcome": "unknown"})]
