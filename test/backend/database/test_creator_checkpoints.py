# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Creator checkpoints enforce message ownership and a single active parent."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from management.db.conversation import repository


@pytest.mark.parametrize(
    "owned,parent",
    [
        (None, None),
        (91, None),
        (91, SimpleNamespace(status="completed")),
    ],
)
def test_checkpoint_rejects_missing_unowned_or_finalized_parent(
    monkeypatch, owned, parent
):
    session = MagicMock()
    session.scalar.side_effect = [owned, parent]

    @contextmanager
    def db():
        yield session

    monkeypatch.setattr(repository, "get_db_session", db)
    with pytest.raises(ValueError):
        repository.checkpoint_creator_message(101, 91, "owner", [], "", "streaming")
    session.execute.assert_not_called()


def test_checkpoint_inserts_ordered_delta_and_terminal_status_in_one_session(
    monkeypatch,
):
    session = MagicMock()
    session.scalar.side_effect = [91, SimpleNamespace(status="streaming")]

    @contextmanager
    def db():
        yield session

    monkeypatch.setattr(repository, "get_db_session", db)
    repository.checkpoint_creator_message(
        101,
        91,
        "owner",
        [
            {
                "unit_index": 3,
                "unit_type": "nl2a",
                "unit_content": "{}",
            }
        ],
        "",
        "completed",
    )
    inserted = session.execute.call_args_list[0].args[1]
    assert inserted[0]["unit_index"] == 3
    assert inserted[0]["created_by"] == "owner"
    assert inserted[0]["message_id"] == 101
    values = session.execute.call_args_list[1].args[0].compile().params
    assert values["status"] == "completed"
