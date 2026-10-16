"""Parent authorization for A2A relation mutations."""

import pytest

from test.backend.services import test_agent_service as legacy
from consts.exceptions import AgentNotFoundError, ForbiddenError
from services import a2a_relation_service as service
from services.agent_draft_permission_service import AgentDraftEditError


@pytest.mark.parametrize("code, error", [
    ("agent_not_found", AgentNotFoundError),
    ("agent_deleted", AgentNotFoundError),
    ("agent_not_draft", AgentNotFoundError),
    ("agent_read_only", ForbiddenError),
])
def test_parent_authorization_failure(mocker, code, error):
    edit = mocker.patch.object(service, "require_agent_draft_edit", side_effect=AgentDraftEditError(code))
    system = mocker.patch.object(service, "is_system_agent")
    with pytest.raises(error):
        service.require_external_relation_edit(1, "tenant", "user")
    edit.assert_called_once_with(agent_id=1, tenant_id="tenant", user_id="user")
    system.assert_not_called()


@pytest.mark.parametrize("system_agent", [False, True])
def test_editable_parent_system_protection(mocker, system_agent):
    mocker.patch.object(service, "require_agent_draft_edit", return_value={"agent_id": 1})
    mocker.patch.object(service, "is_system_agent", return_value=system_agent)
    if system_agent:
        with pytest.raises(ForbiddenError):
            service.require_external_relation_edit(1, "tenant", "user")
    else:
        assert service.require_external_relation_edit(1, "tenant", "user") is None
