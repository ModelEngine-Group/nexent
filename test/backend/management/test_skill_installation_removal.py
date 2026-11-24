# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Installed copies require edit permission and must not be referenced by agents."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from contracts.errors.exceptions import ForbiddenError
from management.services.repository import skill_installations as installs


@pytest.mark.parametrize("repository_id", [None, 42])
@pytest.mark.parametrize("condition", ["missing", "readonly", "referenced", "editable"])
def test_uninstall_checks_identity_permission_and_references(mocker, repository_id, condition):
    session = MagicMock()
    skill = SimpleNamespace(created_by="owner", group_ids="", ingroup_permission="PRIVATE", skill_name="copy")
    session.scalar.side_effect = [None if condition == "missing" else skill, 7 if condition == "referenced" else None]
    mocker.patch("management.db.repository_transactions.repository_unit_of_work", return_value=nullcontext(session))
    mocker.patch.object(installs, "_can_edit_skill", return_value=condition != "readonly")
    service = mocker.patch("management.services.skill.service.SkillService")
    errors = {"missing": LookupError, "readonly": ForbiddenError, "referenced": ValueError}
    if condition in errors:
        with pytest.raises(errors[condition]):
            installs.uninstall_repository_copy(repository_id, 5, "tenant", "user")
        service.assert_not_called()
    else:
        installs.uninstall_repository_copy(repository_id, 5, "tenant", "user")
        service.assert_called_once_with(tenant_id="tenant")
        service.return_value.delete_skill.assert_called_once_with("copy", tenant_id="tenant", user_id="user")
    statement = str(session.scalar.call_args_list[0].args[0])
    assert "tenant_id" in statement and "FOR UPDATE" in statement
    assert ("source_repository_id =" in statement) is (repository_id is not None)
