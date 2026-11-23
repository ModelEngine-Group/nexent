# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SR-005: old Prepared payloads load without reactivating withdrawn source fields."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from contracts.agentos import PreparedHistoryCheckpoint, PreparedHistoryTurn


def test_legacy_checkpoint_source_extensions_are_not_part_of_the_new_contract():
    raw = {'unit_id': 1, 'summary': {'markdown': 'Saved message:42/unit-index:5'},
           'covered_through_message_id': 42, 'execution_sources': [{'message_id': 42, 'content': 'private'}],
           'structured_source_proofs': [{'source_ref': 'message:41/user-message'}]}
    before = deepcopy(raw)
    checkpoint = PreparedHistoryCheckpoint.model_validate(raw)
    assert checkpoint.summary == raw['summary'] and raw == before
    assert 'execution_sources' not in checkpoint.model_dump()
    assert 'structured_source_proofs' not in checkpoint.model_dump()
    with pytest.raises(ValidationError):
        PreparedHistoryCheckpoint.model_validate({**raw, 'unknown_extension': []})


def test_legacy_user_original_is_ignored_while_existing_history_text_is_preserved():
    raw = {'user_message': 'annotated authorized history', 'user_source_content': 'withdrawn raw source',
           'assistant_final_answer': 'done', 'user_message_id': 1, 'assistant_message_id': 2}
    turn = PreparedHistoryTurn.model_validate(raw)
    assert turn.user_message == raw['user_message']
    assert 'user_source_content' not in turn.model_dump()
