# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Group links participate in an API-only batch owner's transaction."""

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from management.db.identity import group


@pytest.mark.parametrize("shared", [True, False])
def test_group_link_uses_shared_session_without_committing(mocker, shared):
    session = MagicMock()
    def flush():
        session.add.call_args.args[0].group_user_id = 42
    session.flush.side_effect = flush
    context = mocker.patch.object(group, "get_db_session", return_value=nullcontext(session))
    assert group.add_user_to_group(7, "api-user", created_by="admin", db_session=session if shared else None) == 42
    if shared:
        context.assert_called_once_with(session)
    else:
        context.assert_called_once_with()
    stored = session.add.call_args.args[0]
    assert (stored.group_id, stored.user_id, stored.created_by, stored.updated_by) == (7, "api-user", "admin", "admin")
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
