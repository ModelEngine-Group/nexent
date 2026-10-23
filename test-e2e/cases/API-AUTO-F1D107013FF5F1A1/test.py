from __future__ import annotations

from decimal import Decimal

import pytest

from shared.http import assert_status, client
from shared.asset_registry import register_asset

pytestmark = [
    pytest.mark.case_id("API-AUTO-F1D107013FF5F1A1"),
    pytest.mark.stage("D2"),
]

_EXPECTED_TERMS = ["citation_alpha", "citation_beta"]
_SCORE_OVERALL = Decimal("12.345678")
_SOURCE_WITH_TERMS = "source-with-highlight-terms"
_SOURCE_WITHOUT_TERMS = "source-without-highlight-terms"


def _seed(user_id: str) -> int:
    from database.conversation_db import (
        create_conversation,
        create_conversation_message,
        create_source_search,
    )

    conversation = create_conversation("d2-retrieval-highlight-terms", user_id)
    conversation_id = int(conversation["conversation_id"])
    register_asset('owned_conversations', str(conversation_id), conversation_id,
                   owner_case_id='API-AUTO-F1D107013FF5F1A1', cleanup={
                       'service': 'runtime', 'identity': 'tenant_a_user',
                       'method': 'DELETE', 'path': f'/conversation/{conversation_id}',
                       'allowed_statuses': [200, 404],
                   })
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

    return conversation_id


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
    conversation_id = _seed(tenant_a_user.user_id)

    async with client("runtime", token=tenant_a_user.access_token) as api:
        try:
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
        finally:
            try:
                await api.delete(f"/conversation/{conversation_id}")
            except Exception:
                pass
