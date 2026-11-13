# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Same-status requests retain ownership and role authorization."""

import pytest

from contracts.errors.exceptions import ForbiddenError, UnauthorizedError

from test.backend.services.test_agent_repository_service import ars
from test.backend.services.test_skill_repository_service import srs
from management.services.repository.agent.publishing import _validate_repository_status_transition as validate_agent


@pytest.mark.parametrize("validate,error_type", [
    (validate_agent, UnauthorizedError),
    (srs._validate_repository_status_transition, ForbiddenError),
])
@pytest.mark.parametrize("role,actor,tenant,allowed", [
    ("ADMIN", "reviewer", "tenant", True),
    ("DEV", "owner", "tenant", True),
    ("SU", "super", "other-tenant", True),
    ("DEV", "other", "tenant", False),
    ("ADMIN", "reviewer", "other-tenant", False),
    ("USER", "owner", "tenant", False),
    ("SPEED", "owner", "tenant", False),
])
def test_same_status_preserves_original_role_and_ownership_gate(validate, error_type, role, actor, tenant, allowed):
    record = {"publisher_tenant_id":"tenant", "publisher_user_id":"owner", "skill_info_json":{"created_by":"owner"}}
    kwargs = dict(user_role=role, current_status="pending_review", new_status="pending_review",
                  record=record, user_id=actor, tenant_id=tenant)
    if allowed:
        assert validate(**kwargs) is None
    else:
        with pytest.raises(error_type, match="[Nn]ot authorized"):
            validate(**kwargs)
