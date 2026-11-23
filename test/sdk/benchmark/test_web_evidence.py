import json

from sdk.benchmark.generic.tools.web_evidence import (
    aggregate_web_evidence,
    build_web_evidence,
)


def test_web_evidence_tracks_search_to_fetch_and_repeated_search():
    steps = [{
        "step_number": 1,
        "web_events": [
            {
                "event_type": "tool_call",
                "tool_name": "exa_search",
                "tool_arguments": {"query": "release date"},
            },
            {
                "event_type": "search_content",
                "content": json.dumps([
                    {"url": "https://example.com/release#notes"},
                ]),
            },
            {
                "event_type": "tool_call",
                "tool_name": "exa_search",
                "tool_arguments": {"query": "release date"},
            },
            {
                "event_type": "search_content",
                "content": json.dumps([
                    {"url": "https://example.com/release"},
                ]),
            },
            {
                "event_type": "tool_call",
                "tool_name": "tavily_extract",
                "tool_arguments": {"url": "https://example.com/release"},
            },
        ],
    }]

    evidence = build_web_evidence(
        steps,
        task_query="When was it released?",
        answer_candidate="FINAL ANSWER: 2024-01-01",
    )

    assert evidence["metrics"]["exa_search_calls"] == 2
    assert evidence["metrics"]["tavily_extract_calls"] == 1
    assert evidence["metrics"]["repeated_search_queries"] == 1
    assert evidence["metrics"]["search_after_url_discovery"] == 1
    assert evidence["metrics"]["fetched_discovered_url_count"] == 1
    assert evidence["semantics"]["direct_support_assessed"] is False
    assert evidence["answer_candidate"] == "FINAL ANSWER: 2024-01-01"
    assert evidence["evidence_ledger"] == [{
        "url": "https://example.com/release",
        "discovered_by": "exa_search",
        "fetched": True,
        "fetch_tools": ["tavily_extract"],
        "directly_supports_answer": None,
    }]
    assert evidence["missing_evidence"] == [
        "semantic_direct_support_not_assessed"
    ]


def test_terminal_curl_is_counted_as_fetch_role():
    evidence = build_web_evidence([{
        "step_number": 2,
        "web_events": [{
            "event_type": "tool_call",
            "tool_name": "terminal",
            "tool_arguments": {
                "command": "curl -L https://example.com/report.pdf",
            },
        }],
    }])

    assert evidence["metrics"]["terminal_calls"] == 1
    assert evidence["metrics"]["terminal_fetch_calls"] == 1
    assert evidence["events"][0]["requested_urls"] == [
        "https://example.com/report.pdf"
    ]


def test_aggregate_reports_items_with_discovery_but_no_fetch():
    first = build_web_evidence([{
        "step_number": 1,
        "web_events": [
            {
                "event_type": "tool_call",
                "tool_name": "exa_search",
                "tool_arguments": {"query": "q"},
            },
            {
                "event_type": "search_content",
                "content": '[{"url": "https://example.com"}]',
            },
        ],
    }])
    second = build_web_evidence([])

    aggregate = aggregate_web_evidence({"a": first, "b": second})

    assert aggregate["item_count"] == 2
    assert aggregate["exa_search_calls"] == 1
    assert aggregate["items_with_discovered_url_but_no_fetch"] == 1
