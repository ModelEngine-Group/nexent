"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")




@STAGE
@pytest.mark.case_id("UT-BE-014")
def test_repository_transition_enforces_owner_and_reviewer_roles() -> None:
    from consts.exceptions import UnauthorizedError
    from services.agent_repository_service import _validate_repository_status_transition

    record = {"publisher_tenant_id": "t1", "publisher_user_id": "dev-1"}
    result = _validate_repository_status_transition(
        user_role="DEV", current_status="not_shared", new_status="pending_review",
        record=record, user_id="dev-1", tenant_id="t1",
    )
    assert result == {"publisher_tenant_id": "t1", "publisher_user_id": "dev-1"}
    with pytest.raises(UnauthorizedError):
        _validate_repository_status_transition(
            user_role="DEV", current_status="not_shared", new_status="pending_review",
            record=record, user_id="dev-2", tenant_id="t1",
        )
    with pytest.raises(ValueError):
        _validate_repository_status_transition(
            user_role="SU", current_status="not_shared", new_status="approved",
            record=record, user_id="su", tenant_id="root",
        )






















