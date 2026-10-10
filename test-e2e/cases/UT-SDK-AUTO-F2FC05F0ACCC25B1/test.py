import json

import pytest

from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
from nexent.core.utils.tools_common_message import (
    KnowledgeSearchScope,
    SearchResultTextMessage,
    build_knowledge_search_response,
    resolve_knowledge_search_scope,
)


@pytest.mark.case_id("UT-SDK-AUTO-F2FC05F0ACCC25B1")
@pytest.mark.stage("D1")
def test_knowledge_base_search_scope_and_structured_response():
    configured = ["kb_a", "kb_b", "kb_c", "kb_d"]
    available = ["kb_a", "kb_c"]

    no_scope = resolve_knowledge_search_scope(
        configured_scope=configured,
        available_scope=available,
        requested_scope=None,
    )
    assert isinstance(no_scope, KnowledgeSearchScope)
    assert no_scope.used_scope == ["kb_a", "kb_c"]
    assert no_scope.permission_denied_scope == []
    assert no_scope.unavailable_scope == []
    assert no_scope.fallback_to_all is False
    assert no_scope.scope_was_specified is False

    empty_scope = resolve_knowledge_search_scope(
        configured_scope=configured,
        available_scope=available,
        requested_scope=[],
    )
    assert empty_scope.used_scope == ["kb_a", "kb_c"]
    assert empty_scope.permission_denied_scope == []
    assert empty_scope.unavailable_scope == []
    assert empty_scope.fallback_to_all is False
    assert empty_scope.scope_was_specified is False

    specified = resolve_knowledge_search_scope(
        configured_scope=configured,
        available_scope=available,
        requested_scope=["kb_a", "kb_b", "kb_x"],
    )
    assert specified.used_scope == ["kb_a"]
    assert specified.permission_denied_scope == ["kb_b"]
    assert specified.unavailable_scope == ["kb_x"]
    assert specified.fallback_to_all is False
    assert specified.scope_was_specified is True

    fallback = resolve_knowledge_search_scope(
        configured_scope=configured,
        available_scope=available,
        requested_scope=["kb_b"],
    )
    assert fallback.used_scope == ["kb_a", "kb_c"]
    assert fallback.permission_denied_scope == ["kb_b"]
    assert fallback.unavailable_scope == []
    assert fallback.fallback_to_all is True
    assert fallback.scope_was_specified is True

    tracking_disabled = resolve_knowledge_search_scope(
        configured_scope=configured,
        available_scope=available,
        requested_scope=["kb_a", "kb_b", "kb_x"],
        permission_tracking_enabled=False,
    )
    assert tracking_disabled.used_scope == ["kb_a"]
    assert tracking_disabled.permission_denied_scope == []
    assert tracking_disabled.unavailable_scope == ["kb_x"]
    assert tracking_disabled.fallback_to_all is False
    assert tracking_disabled.scope_was_specified is True

    tracking_disabled_fallback = resolve_knowledge_search_scope(
        configured_scope=configured,
        available_scope=available,
        requested_scope=["kb_b"],
        permission_tracking_enabled=False,
    )
    assert tracking_disabled_fallback.used_scope == ["kb_a", "kb_c"]
    assert tracking_disabled_fallback.permission_denied_scope == []
    assert tracking_disabled_fallback.fallback_to_all is True

    no_available = resolve_knowledge_search_scope(
        configured_scope=["kb_a"],
        available_scope=[],
        requested_scope=["kb_a"],
    )
    assert no_available.used_scope == []
    assert no_available.permission_denied_scope == ["kb_a"]
    assert no_available.unavailable_scope == []
    assert no_available.fallback_to_all is False

    deduped = resolve_knowledge_search_scope(
        configured_scope=["kb_a", "kb_a", "kb_b"],
        available_scope=["kb_a"],
        requested_scope=["kb_a", "kb_a"],
    )
    assert deduped.used_scope == ["kb_a"]
    assert deduped.permission_denied_scope == []
    assert deduped.unavailable_scope == []

    branch_filtered_no_used = build_knowledge_search_response(
        results=[],
        used_scope=[],
        permission_denied_scope=["kb_b"],
        unavailable_scope=["kb_x"],
        fallback_to_all=False,
        scope_was_specified=True,
    )
    payload = json.loads(branch_filtered_no_used)
    assert set(payload.keys()) == {"notice", "results"}
    assert payload["results"] == []
    assert payload["notice"] == (
        'NOTICE: Requested knowledge bases were filtered (no read permission: ["kb_b"]; '
        'not configured or unavailable: ["kb_x"]). No accessible knowledge bases remained, '
        'so search was not executed.'
    )

    branch_no_used_no_filter = build_knowledge_search_response(
        results=[],
        used_scope=[],
        permission_denied_scope=[],
        unavailable_scope=[],
        fallback_to_all=False,
        scope_was_specified=False,
    )
    payload = json.loads(branch_no_used_no_filter)
    assert payload["notice"] == (
        "NOTICE: No configured knowledge bases are accessible, so search was not executed."
    )

    branch_fallback = build_knowledge_search_response(
        results=[],
        used_scope=["kb_a", "kb_c"],
        permission_denied_scope=["kb_b"],
        unavailable_scope=[],
        fallback_to_all=True,
        scope_was_specified=True,
    )
    payload = json.loads(branch_fallback)
    assert payload["notice"] == (
        'NOTICE: Requested knowledge bases were filtered (no read permission: ["kb_b"]). '
        'Search was broadened to all available configured knowledge bases ["kb_a", "kb_c"]. '
        "Do not retry the filtered knowledge bases. No relevant information was found."
    )

    branch_filtered_remaining = build_knowledge_search_response(
        results=[],
        used_scope=["kb_a"],
        permission_denied_scope=["kb_b"],
        unavailable_scope=["kb_x"],
        fallback_to_all=False,
        scope_was_specified=True,
    )
    payload = json.loads(branch_filtered_remaining)
    assert payload["notice"] == (
        'NOTICE: Requested knowledge bases were filtered (no read permission: ["kb_b"]; '
        'not configured or unavailable: ["kb_x"]). Search was executed in the remaining '
        'available knowledge bases ["kb_a"]. Do not retry the filtered knowledge bases. '
        'No relevant information was found.'
    )

    branch_specified = build_knowledge_search_response(
        results=[],
        used_scope=["kb_a"],
        permission_denied_scope=[],
        unavailable_scope=[],
        fallback_to_all=False,
        scope_was_specified=True,
    )
    payload = json.loads(branch_specified)
    assert payload["notice"] == (
        "NOTICE: Search was executed in the requested knowledge bases. "
        "No relevant information was found."
    )

    branch_unspecified = build_knowledge_search_response(
        results=[],
        used_scope=["kb_a"],
        permission_denied_scope=[],
        unavailable_scope=[],
        fallback_to_all=False,
        scope_was_specified=False,
    )
    payload = json.loads(branch_unspecified)
    assert payload["notice"] == (
        "NOTICE: No knowledge-base scope was specified. Search was executed using the "
        "agent's configured accessible knowledge bases. No relevant information was found."
    )

    empty_results_notice = build_knowledge_search_response(
        results=[],
        used_scope=["kb_a"],
        permission_denied_scope=[],
        unavailable_scope=[],
        fallback_to_all=False,
        scope_was_specified=True,
    )
    payload = json.loads(empty_results_notice)
    assert payload["notice"] == (
        "NOTICE: Search was executed in the requested knowledge bases. "
        "No relevant information was found."
    )

    message = SearchResultTextMessage(
        title="title",
        url="url",
        text="text",
        tool_sign="a",
        cite_index=3,
    )
    model_dict = message.to_model_dict()
    assert model_dict["reference_mark"] == "[[a3]]"
    assert model_dict["index"] == "a3"

    tool = KnowledgeBaseSearchTool.__new__(KnowledgeBaseSearchTool)
    tool.display_name_to_index_map = {"知识库A": "index_a", "知识库B": "index_b"}
    assert tool._convert_to_display_names(["index_a", "index_b", "index_unknown"]) == [
        "知识库A",
        "知识库B",
        "index_unknown",
    ]

    tool_no_map = KnowledgeBaseSearchTool.__new__(KnowledgeBaseSearchTool)
    tool_no_map.display_name_to_index_map = {}
    assert tool_no_map._convert_to_display_names(["index_a"]) == ["index_a"]

    tool_none_map = KnowledgeBaseSearchTool.__new__(KnowledgeBaseSearchTool)
    tool_none_map.display_name_to_index_map = None
    assert tool_none_map._convert_to_display_names(["index_a"]) == ["index_a"]

    tool_display_response = KnowledgeBaseSearchTool.__new__(KnowledgeBaseSearchTool)
    tool_display_response.display_name_to_index_map = {"知识库A": "index_a"}
    display_response = tool_display_response._build_scope_response(
        results=[],
        used_scope=[],
        permission_denied_scope=["index_a"],
        unavailable_scope=[],
        fallback_to_all=False,
        scope_was_specified=True,
    )
    display_payload = json.loads(display_response)
    assert 'no read permission: ["知识库A"]' in display_payload["notice"]
    assert "index_a" not in display_payload["notice"]

    configured_before = list(configured)
    available_before = list(available)
    requested_before = ["kb_a", "kb_b", "kb_x"]
    first = resolve_knowledge_search_scope(configured, available, requested_before)
    second = resolve_knowledge_search_scope(configured, available, requested_before)
    assert first == second
    assert configured == configured_before
    assert available == available_before
    assert requested_before == ["kb_a", "kb_b", "kb_x"]
