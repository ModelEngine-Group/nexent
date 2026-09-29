import json
import logging
import uuid

import pytest
from sqlalchemy import func, select

from database.client import get_db_session
from database.conversation_db import (
    HistorySummaryPersistenceError,
    create_conversation,
    create_conversation_message,
    delete_conversation,
)
from database.db_models import ConversationMessageUnit
from services.conversation_management_service import (
    load_historical_context,
    persist_history_summary_candidate,
)
from shared.asset_registry import register_asset


def _setup_conversation(user_id, run_id, tag, assistant_status="completed"):
    conversation = create_conversation(f"{run_id}-{tag}", user_id=user_id)
    conversation_id = int(conversation["conversation_id"])
    register_asset('owned_conversations', str(conversation_id), conversation_id,
                   owner_case_id='API-AUTO-65B7BDD10507AA51', cleanup={
                       'service': 'runtime', 'identity': 'tenant_a_user',
                       'method': 'DELETE', 'path': f'/conversation/{conversation_id}',
                       'allowed_statuses': [200, 404],
                   })
    user_message_id = create_conversation_message(
        {
            "conversation_id": conversation_id,
            "message_idx": 0,
            "role": "user",
            "content": f"{tag} user message",
        },
        user_id=user_id,
        status="completed",
    )
    assistant_message_id = create_conversation_message(
        {
            "conversation_id": conversation_id,
            "message_idx": 1,
            "role": "assistant",
            "content": f"{tag} assistant message",
        },
        user_id=user_id,
        status=assistant_status,
    )
    return conversation_id, user_message_id, assistant_message_id


def _count_history_summary_units(conversation_id):
    with get_db_session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ConversationMessageUnit)
            .where(
                ConversationMessageUnit.conversation_id == int(conversation_id),
                ConversationMessageUnit.unit_type == "history_summary",
                ConversationMessageUnit.delete_flag == "N",
            )
        )
    return int(count or 0)


def _read_unit(unit_id):
    with get_db_session() as session:
        row = session.execute(
            select(
                ConversationMessageUnit.unit_type,
                ConversationMessageUnit.unit_status,
                ConversationMessageUnit.unit_content,
            ).where(
                ConversationMessageUnit.unit_id == int(unit_id),
                ConversationMessageUnit.delete_flag == "N",
            )
        ).one()
    return {
        "unit_type": row.unit_type,
        "unit_status": row.unit_status,
        "unit_content": row.unit_content,
    }


@pytest.mark.case_id("API-AUTO-65B7BDD10507AA51")
@pytest.mark.stage("D3")
async def test_persist_history_summary_compaction_metrics(tenant_a_user, caplog):
    identity = tenant_a_user
    user_id = identity.user_id
    tenant_id = identity.tenant_id
    run_id = f"API-AUTO-65B7BDD10507AA51-{uuid.uuid4().hex[:12]}"

    conversation_ids = []
    try:
        conversation_id, _user_message_id, assistant_message_id = _setup_conversation(
            user_id, run_id, "core"
        )
        conversation_ids.append(conversation_id)

        neg_cover_id, _u1, neg_cover_assistant = _setup_conversation(
            user_id, run_id, "neg-cover", assistant_status="streaming"
        )
        conversation_ids.append(neg_cover_id)

        neg_summary_id, _u2, neg_summary_assistant = _setup_conversation(
            user_id, run_id, "neg-summary"
        )
        conversation_ids.append(neg_summary_id)

        caplog.set_level(logging.DEBUG)

        bad_cover = {
            "summary": {"note": "coverage must be a completed assistant"},
            "covered_through_message_id": neg_cover_assistant,
        }
        with pytest.raises(HistorySummaryPersistenceError):
            persist_history_summary_candidate(
                neg_cover_id, bad_cover, user_id, tenant_id
            )
        assert _count_history_summary_units(neg_cover_id) == 0

        bad_summary = {
            "summary": "not-a-dict",
            "covered_through_message_id": neg_summary_assistant,
        }
        with pytest.raises(HistorySummaryPersistenceError):
            persist_history_summary_candidate(
                neg_summary_id, bad_summary, user_id, tenant_id
            )
        assert _count_history_summary_units(neg_summary_id) == 0

        summary = {
            "title": "compacted summary",
            "body": "concise recap of earlier turns",
        }
        metric_values = {
            "history_tokens_before": 12000,
            "history_tokens_after": 3500,
            "compaction_attempts": 2,
            "compaction_trigger_threshold_tokens": 10000,
            "compaction_target_tokens": 4000,
        }
        good_candidate = {
            "summary": summary,
            "covered_through_message_id": assistant_message_id,
            "trigger": "context_window_threshold",
            **metric_values,
        }

        with pytest.raises(HistorySummaryPersistenceError):
            persist_history_summary_candidate(
                conversation_id, good_candidate, "", tenant_id
            )
        with pytest.raises(HistorySummaryPersistenceError):
            persist_history_summary_candidate(
                conversation_id, good_candidate, user_id, ""
            )
        with pytest.raises(HistorySummaryPersistenceError):
            persist_history_summary_candidate(
                conversation_id, good_candidate, user_id, "wrong-tenant-id"
            )
        assert _count_history_summary_units(conversation_id) == 0

        unit_id = persist_history_summary_candidate(
            conversation_id, good_candidate, user_id, tenant_id
        )
        assert isinstance(unit_id, int) and unit_id > 0

        persisted = _read_unit(unit_id)
        assert persisted["unit_type"] == "history_summary"
        assert persisted["unit_status"] == "completed"
        payload = json.loads(persisted["unit_content"])
        assert payload["summary"] == summary
        assert payload["covered_through_message_id"] == assistant_message_id
        assert payload["trigger"] == "context_window_threshold"

        current_user_message_id = create_conversation_message(
            {
                "conversation_id": conversation_id,
                "message_idx": 2,
                "role": "user",
                "content": "follow up question",
            },
            user_id=user_id,
            status="completed",
        )

        loaded = load_historical_context(
            conversation_id, current_user_message_id, user_id, tenant_id
        )
        assert loaded is not None
        history_summary = loaded.get("history_summary")
        assert history_summary is not None
        assert history_summary["summary"] == summary
        assert history_summary["covered_through_message_id"] == assistant_message_id
        assert history_summary["trigger"] == "context_window_threshold"
        for key, expected in metric_values.items():
            assert history_summary[key] == expected
            assert isinstance(history_summary[key], int)

        secrets = [
            value
            for value in (identity.access_token, identity.password, identity.refresh_token)
            if value
        ]
        for record in caplog.records:
            message = record.getMessage()
            for secret in secrets:
                assert secret not in message
    finally:
        for conversation_id in conversation_ids:
            try:
                delete_conversation(conversation_id, user_id=user_id)
            except Exception:
                pass
