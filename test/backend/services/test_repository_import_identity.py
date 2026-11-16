# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Repository imports preserve authenticated user and tenant identity."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from test.backend.services.test_agent_repository_service import _repository_record
from contracts.errors.exceptions import UnauthorizedError
from management.services.repository.agent import installation


@pytest.mark.asyncio
@pytest.mark.parametrize("with_skills", [False, True])
@pytest.mark.parametrize("return_root_id", [False, True])
async def test_repository_import_passes_identity_to_typed_importer(with_skills, return_root_id):
    snapshot = {
        "agent_id": 10,
        "agent_info": {"10": {"name": "template"}},
        "mcp_info": [],
        "skills": [{"skill_name": "helper", "skill_zip_base64": "payload"}] if with_skills else [],
    }
    record = {**_repository_record(agent_repository_id=42), "agent_info_json": snapshot}

    async def typed_import(*args, **kwargs):
        identity = args[2] if with_skills else args[1]
        assert identity.user_id == "copier"
        assert identity.tenant_id == "target-tenant"
        assert kwargs["resolve_name_conflicts"] is True
        return {10: 101}

    importer = "import_agent_with_skills_impl" if with_skills else "import_agent_impl"
    with patch.object(installation, "get_agent_repository_by_id", return_value=record), \
            patch.object(installation, importer, new=AsyncMock(side_effect=typed_import)), \
            patch.object(installation, "increment_agent_repository_downloads", return_value=1) as increment:
        result = await installation.import_agent_from_repository_impl(
            42, "target-tenant", "Bearer session", user_id="copier", return_root_id=return_root_id
        )
    assert result == ({"agent_id": 101} if return_root_id else {10: 101})
    increment.assert_called_once_with(42)


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated_tenant", ["target-tenant", "other-tenant", None])
async def test_repository_import_resolves_missing_user_and_rejects_invalid_identity(authenticated_tenant):
    record = {
        **_repository_record(),
        "agent_info_json": {"agent_id": 10, "agent_info": {"10": {"name": "template"}}, "mcp_info": []},
    }
    auth = ModuleType("gateway.authentication.auth")
    auth.get_current_user_id = MagicMock(return_value=("copier", authenticated_tenant))
    if authenticated_tenant is None:
        auth.get_current_user_id.side_effect = UnauthorizedError("Session expired")
    with patch.dict(sys.modules, {"gateway.authentication.auth": auth}), \
            patch.object(installation, "get_agent_repository_by_id", return_value=record), \
            patch.object(installation, "import_agent_impl", new=AsyncMock(return_value={10: 101})) as importer, \
            patch.object(installation, "increment_agent_repository_downloads", return_value=1) as increment:
        if authenticated_tenant == "target-tenant":
            result = await installation.import_agent_from_repository_impl(42, "target-tenant", "Bearer session")
            assert result == {10: 101}
            assert importer.await_args.args[1].user_id == "copier"
            assert importer.await_args.args[1].tenant_id == "target-tenant"
            increment.assert_called_once_with(42)
        else:
            with pytest.raises(UnauthorizedError):
                await installation.import_agent_from_repository_impl(42, "target-tenant", "Bearer session")
            importer.assert_not_awaited()
            increment.assert_not_called()
    auth.get_current_user_id.assert_called_once_with("Bearer session")
