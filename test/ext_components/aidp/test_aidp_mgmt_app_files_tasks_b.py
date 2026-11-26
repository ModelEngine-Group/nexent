# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP management route tests (split by feature from the original suite)."""

from test.ext_components.aidp.test_aidp_mgmt_app import *  # noqa: F401,F403
from test.ext_components.aidp.test_aidp_mgmt_app import (  # noqa: F401
    _bearer,
    _build_app,
    _client,
    _isolated_imports,
    configure_aidp_constants,
)

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException

import pytest

pytestmark = pytest.mark.usefixtures("configure_aidp_constants")


class TestUploadTaskRetryEndpoint:
    """POST /knowledge-bases/{kds_id}/upload-tasks/retry."""

    def test_retry_delegates_selected_file_validation_to_aidp(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        file_uuid = "00000000000040008000000000000003"
        upstream_result = {
            "success_list": [{"file_uuid": file_uuid}],
            "failed_list": [],
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "list_aidp_doc_history_impl",
                          side_effect=AssertionError("retry must not scan history")), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl",
                          return_value=upstream_result) as retry_docs:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": [file_uuid]},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == upstream_result
        retry_docs.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", [file_uuid])

    def test_retry_requires_edit_permission(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        # Exercise the real permission matrix: a DEV user who matched the
        # record's group resolves to READ_ONLY, which must not satisfy the
        # endpoint's EDIT requirement.
        readonly_row = {
            "kb_id": "kb-1",
            "owner_user_id": "another-owner",
            "ingroup_permission": "READ_ONLY",
            "group_ids": [7],
        }
        with patch.object(aidp_permission_service, "_get_permission_record",
                          return_value=readonly_row), \
             patch.object(aidp_permission_service, "_get_user_role",
                          return_value="DEV"), \
             patch.object(aidp_permission_service, "_get_user_groups",
                          return_value=[7]), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl") as retry_docs:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": ["00000000000040008000000000000003"]},
            )
        assert response.status_code == HTTPStatus.FORBIDDEN
        retry_docs.assert_not_called()

    def test_retry_dedupes_file_uuids(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        first = "00000000000040008000000000000003"
        second = "00000000000040008000000000000004"
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl",
                          return_value={"success_list": [], "failed_list": []}) as retry_docs:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": [first, second, first]},
            )

        assert response.status_code == HTTPStatus.OK
        retry_docs.assert_called_once_with(SERVER_URL, API_KEY, "kb-1", [first, second])

    def test_retry_rejects_empty_uuid_list(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": []},
            )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_retry_invalidates_detail_and_count_caches(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "retry_aidp_docs_impl",
                          return_value={"success_list": [], "failed_list": []}), \
             patch.object(aidp_mgmt_app, "invalidate_aidp_kb_detail_cache") as kb_cache, \
             patch.object(aidp_mgmt_app, "invalidate_aidp_doc_count_cache") as count_cache:
            response = client.post(
                "/aidp-mgmt/knowledge-bases/kb-1/upload-tasks/retry",
                headers=_bearer(),
                json={"file_uuids": ["00000000000040008000000000000003"]},
            )

        assert response.status_code == HTTPStatus.OK
        kb_cache.assert_called_once_with(SERVER_URL, API_KEY, "kb-1")
        count_cache.assert_called_once_with(SERVER_URL, API_KEY, "kb-1")


