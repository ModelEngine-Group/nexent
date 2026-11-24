# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AgentNotFoundError, AppException, ForbiddenError
from management.services.evaluation import evolution_access


@pytest.mark.parametrize(("failure", "code", "status"), [
    (AgentNotFoundError("agent is outside the caller's tenant"), ErrorCode.COMMON_RESOURCE_NOT_FOUND, 404),
    (ForbiddenError("agent is read-only"), ErrorCode.COMMON_FORBIDDEN, 403),
])
def test_business_agent_error_matches_replay_access_contract(mocker, failure, code, status):
    mocker.patch.object(evolution_access, "get_user_role_by_tenant", return_value="ADMIN")
    authorize = mocker.patch.object(evolution_access, "authorize_debug_version", side_effect=failure)

    with pytest.raises(AppException) as caught:
        evolution_access.require_business_agent_edit(3, "tenant", "actor")

    assert caught.value.error_code == code
    assert caught.value.http_status == status
    authorize.assert_called_once_with(3, 0, "actor", "tenant")
