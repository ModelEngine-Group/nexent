# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.http import assert_status, client
from shared.factories.conversation import owned_conversation

pytestmark = [
    pytest.mark.case_id("API-AUTO-F1D107013FF5F1A1"),
    pytest.mark.stage("D2"),
]

_EXPECTED_TERMS = ["citation_alpha", "citation_beta"]
_SCORE_OVERALL = Decimal("12.345678")
_SOURCE_WITH_TERMS = "source-with-highlight-terms"
_SOURCE_WITHOUT_TERMS = "source-without-highlight-terms"


def _seed_sources(conversation_id: int, user_id: str) -> None:
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.db.conversation.repository import create_conversation_message, create_source_search

    load_system_configuration()
    message_id = create_conversation_message(
        {
            "conversation_id": conversation_id,
            "message_idx": 1,
            "role": "assistant",
            "content": "assistant answer",
        },
        user_id,
    )

    create_source_search(
        {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "source_type": "search",
            "source_title": _SOURCE_WITH_TERMS,
            "source_location": "https://example.com/with-terms",
            "source_content": "content that contains the highlighted terms",
            "cite_index": 1,
            "search_type": "web_search",
            "tool_sign": "web",
            "score_overall": _SCORE_OVERALL,
            "score_accuracy": Decimal("0.900000"),
            "score_semantic": Decimal("0.800000"),
            "retrieval_highlight_terms": list(_EXPECTED_TERMS),
        },
        user_id,
    )

    create_source_search(
        {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "source_type": "search",
            "source_title": _SOURCE_WITHOUT_TERMS,
            "source_location": "https://example.com/without-terms",
            "source_content": "content without highlighted terms",
            "cite_index": 2,
            "search_type": "web_search",
            "tool_sign": "web",
            "score_overall": Decimal("0.500000"),
            "score_accuracy": Decimal("0.400000"),
        },
        user_id,
    )


def _assistant_message(messages):
    for message in messages:
        if message.get("role") == "assistant":
            return message
    raise AssertionError("history contains no assistant message")


def _search_item(items, title):
    for item in items:
        if item.get("title") == title:
            return item
    raise AssertionError(f"search item {title!r} not found")


async def test_retrieval_highlight_terms_contract(tenant_a_user):
    async with (
        owned_conversation(tenant_a_user, "d2-retrieval-highlight-terms") as conversation_id,
        client("runtime", token=tenant_a_user.access_token) as api,
    ):
        _seed_sources(conversation_id, tenant_a_user.user_id)
        history = await api.get(f"/conversation/{conversation_id}")
        assert_status(history, 200)
        body = history.json()
        assert body["code"] == 0
        assert isinstance(body["data"], list) and body["data"]

        entry = body["data"][0]
        assistant = _assistant_message(entry["message"])
        with_terms = _search_item(assistant["search"], _SOURCE_WITH_TERMS)
        without_terms = _search_item(assistant["search"], _SOURCE_WITHOUT_TERMS)

        assert with_terms["score_details"]["retrieval_highlight_terms"] == _EXPECTED_TERMS
        assert float(with_terms["score"]) == pytest.approx(float(_SCORE_OVERALL), abs=1e-9)
        assert "retrieval_highlight_terms" not in without_terms["score_details"]

        sources = await api.post(
            "/conversation/sources",
            json={"conversation_id": conversation_id, "type": "search"},
        )
        assert_status(sources, 200)
        sources_body = sources.json()
        assert sources_body["code"] == 0
        searches = sources_body["data"]["searches"]

        src_with = _search_item(searches, _SOURCE_WITH_TERMS)
        src_without = _search_item(searches, _SOURCE_WITHOUT_TERMS)
        assert src_with["score_details"]["retrieval_highlight_terms"] == _EXPECTED_TERMS
        assert float(src_with["score"]) == pytest.approx(float(_SCORE_OVERALL), abs=1e-9)
        assert "retrieval_highlight_terms" not in src_without["score_details"]

        reloaded = await api.get(f"/conversation/{conversation_id}")
        assert_status(reloaded, 200)
        reloaded_entry = reloaded.json()["data"][0]
        reloaded_assistant = _assistant_message(reloaded_entry["message"])
        reloaded_with = _search_item(reloaded_assistant["search"], _SOURCE_WITH_TERMS)
        reloaded_without = _search_item(reloaded_assistant["search"], _SOURCE_WITHOUT_TERMS)
        assert reloaded_with["score_details"]["retrieval_highlight_terms"] == _EXPECTED_TERMS
        assert "retrieval_highlight_terms" not in reloaded_without["score_details"]
