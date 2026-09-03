from nexent.core.models.provider_usage import NormalizedTokenUsage, ProviderCallUsage
from nexent.core.models.usage_aggregation import aggregate_turn_usage


def _record(call_id, input_tokens, output_tokens, *, purpose="main_agent", source="provider", status="completed"):
    return ProviderCallUsage(
        call_id=call_id,
        purpose=purpose,
        source=source,
        status=status,
        usage=NormalizedTokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(input_tokens + output_tokens) if input_tokens is not None and output_tokens is not None else None,
        ),
    )


def test_ac_tu_004_deduplicates_replayed_calls_and_aggregates_once():
    partial = _record("one", 10, None, status="partial")
    completed = _record("one", 10, 2)
    second = _record("two", 20, 3)

    summary = aggregate_turn_usage([partial, completed, second], context_limit_tokens=100)

    assert summary["schema_version"] == 3
    assert summary["call_count"] == 2
    assert summary["usage"]["input_tokens"] == 30
    assert summary["usage"]["output_tokens"] == 5
    assert summary["usage"]["total_tokens"] == 35


def test_ac_tu_004_partial_sum_never_impersonates_complete_total():
    summary = aggregate_turn_usage([_record("one", 10, 2), _record("two", 20, None)])

    assert summary["usage"]["input_tokens"] == 30
    assert summary["usage"]["output_tokens"] is None
    assert summary["known_field_call_counts"]["output_tokens"] == 1


def test_ac_tu_005_context_pressure_uses_latest_and_peak_not_sum():
    summary = aggregate_turn_usage(
        [
            _record("one", 80, 2),
            _record("summary", 200, 5, purpose="history_summary"),
            _record("two", 50, 3, purpose="final_answer"),
        ],
        context_limit_tokens=1000,
    )

    assert summary["usage"]["input_tokens"] == 330
    assert summary["peak_context"] == {"call_id": "one", "input_tokens": 80, "limit_tokens": 1000}
    assert summary["latest_context"] == {"call_id": "two", "input_tokens": 50, "limit_tokens": 1000}


def test_p10_ac_001_estimated_legacy_calls_do_not_define_context_pressure():
    summary = aggregate_turn_usage(
        [_record("legacy", 900, 20, source="estimated")],
        context_limit_tokens=1000,
    )

    assert summary["latest_context"] is None
    assert summary["peak_context"] is None
