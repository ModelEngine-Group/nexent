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


class TestUpdateGraphConfigDegradedStorage:
    """The stored graph_config shape never leaks into the PATCH payload."""

    @pytest.mark.parametrize(
        "stored",
        ["not valid json", "[1, 2]", None, {"domain": "通用"}],
    )
    def test_stored_config_shape_does_not_affect_patch_payload(self, stored):
        from ext_components.aidp.services import aidp_permission_service
        """Only edited fields are sent, so unparseable or legacy stored
        configs cannot break or pollute the update."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        current = {"kds_id": "kb-1", "is_exist_graph": True}
        if stored is not None:
            current["graph_config"] = stored
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": {"llm_model_name": "gpt-4o"}},
            )

        assert response.status_code == HTTPStatus.OK
        payload = mock_update.call_args.args[3]
        assert payload["graph_config"] == json.dumps(
            {"llm_model_name": "gpt-4o"}, ensure_ascii=False
        )
        assert payload["is_exist_graph"] is True


class TestSetPermissionBlankName:
    def test_set_permission_rejects_blank_name(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "save_kb_settings") as mock_save:
            response = client.patch(
                "/aidp-mgmt/aidp-permissions/kb-1",
                headers=_bearer(),
                json={"ingroup_permission": "PRIVATE", "name": "   "},
            )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        mock_save.assert_not_called()


class TestNormalizeKbConfigFieldsEdgeCases:
    """Merge precedence and graph normalization edge branches."""

    def test_blank_or_non_string_kms_config_str_is_ignored(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        for raw in ("   ", 123, None):
            detail = {"kms_config_str": raw, "kds_id": "kb-1"}
            out = aidp_mgmt_app._normalize_kb_config_fields(detail)
            assert "chunk_mode" not in out

    def test_top_level_value_wins_over_kms_config_str(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "kms_config_str": '{"embedding_model": "nested"}',
            "embedding_model": "top-level",
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["embedding_model"] == "top-level"

    def test_kms_config_str_fills_none_valued_top_level_keys(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "kms_config_str": '{"embedding_model": "nested"}',
            "embedding_model": None,
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["embedding_model"] == "nested"

    def test_non_digit_hop_is_kept_verbatim(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "graph_config": json.dumps({"retrieve_subgraph_hop": "auto"}),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["graph_config"]["retrieve_subgraph_hop"] == "auto"

    def test_blank_nested_llm_model_is_not_lifted(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "graph_config": json.dumps(
                {"llm_model_name": "   ", "no_think_mode": "是"}, ensure_ascii=False
            ),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert "llm_model_name" not in out
        assert out["graph_config"]["no_think_mode"] is True

    def test_kms_config_str_with_non_dict_json_is_ignored(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {"kms_config_str": "[1, 2]"}
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert "chunk_mode" not in out


class TestDeleteKnowledgeBaseFailure:
    """An upstream delete failure leaves local permission state untouched."""

    def test_delete_reports_failure_and_skips_local_cleanup(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "delete_aidp_kb_impl",
                          return_value=False), \
             patch.object(aidp_permission_service, "soft_delete_permission") as mock_soft:
            response = client.delete(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"success": False}
        mock_soft.assert_not_called()



