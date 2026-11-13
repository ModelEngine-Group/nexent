# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression for prepared repository files when installation upload fails."""

import io
from unittest.mock import MagicMock, patch
import zipfile

import pytest

from test.backend.services.test_skill_service import create_test_service, skill_service


@pytest.mark.parametrize("failure_stage", ["save", "upload"])
def test_repository_install_cleans_prepared_files_before_database_write(failure_stage):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("sample/SKILL.md", "---\nname: sample\ndescription: Sample\n---\nBody")
    service = create_test_service()
    service.skill_manager = MagicMock()
    service._resolve_local_skills_dir_for_overlay = lambda: None
    failure = RuntimeError("Controlled preparation failure")
    if failure_stage == "save":
        service.skill_manager.save_skill.side_effect = failure
    with patch.object(skill_service.skill_db, "get_skill_by_name", return_value=None), patch.object(
        skill_service.skill_db, "create_skill"
    ) as create, patch.object(service, "_delete_local_skill_files") as cleanup, patch.object(
        service, "_upload_zip_files", side_effect=failure if failure_stage == "upload" else None
    ):
        with pytest.raises(RuntimeError, match="Controlled preparation failure"):
            service._save_skill_upload(stream.getvalue(), "sample", "zip", tenant_id="test-tenant",
                user_id="actor", source="repository", source_repository_id=42)
    cleanup.assert_called_once_with("sample", tenant_id="test-tenant")
    create.assert_not_called()
