"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")












@STAGE
@pytest.mark.case_id("UT-BE-018")
def test_selected_share_messages_form_an_independent_snapshot() -> None:
    from services.conversation_share_service import _select_message_pairs

    original = [
        {"role": "user", "message_id": 1, "content": "q1"},
        {"role": "assistant", "message_id": 2, "content": "a1"},
        {"role": "user", "message_id": 3, "content": "q2"},
        {"role": "assistant", "message_id": 4, "content": "a2"},
    ]
    selected = _select_message_pairs(original, [3])
    assert [item["message_id"] for item in selected] == [3, 4]
    assert _select_message_pairs(original, []) is original














