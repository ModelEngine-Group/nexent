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


class TestUpdateKbConfigurationFields:
    """VLM / chunk settings carried by UpdateKbRequest (detail settings modal)."""

    def test_update_forwards_vlm_and_chunk_settings(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        payload = {
            "chunk_mode": 1,
            "chunk_token_num": 512,
            "chunk_overlap_num": 51,
            "topk": 5,
            "caption_enable": 1,
            "vlm_model": "qwen2-vl-7b",
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json=payload,
            )

        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        assert mock_update.call_args.args[2] == "kb-1"
        assert mock_update.call_args.args[3] == payload

    def test_update_rejects_out_of_range_chunk_settings(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()

        payloads = [
            {"chunk_mode": 2},
            {"chunk_token_num": 255},
            {"chunk_token_num": 4097},
            {"chunk_overlap_num": 1.5},
            {"chunk_token_num": 512, "chunk_overlap_num": 257},
        ]
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")):
            for payload in payloads:
                response = client.put(
                    "/aidp-mgmt/knowledge-bases/kb-1",
                    headers=_bearer(),
                    json=payload,
                )
                assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    # ---- Knowledge graph settings (detail information tab) ----

    def test_update_sends_only_edited_graph_fields_with_enabled_flag(self):
        from ext_components.aidp.services import aidp_permission_service
        """A partial graph_config edit forwards only the edited fields in
        AIDP string format, and echoes is_exist_graph=true which AIDP
        requires alongside any graph_config PATCH."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        current_graph = {
            "domain": "通用",
            "prompt_language": "中文",
            "prompt_text": "default prompt",
            "llm_model_name": "qwen-max",
            "retrieve_subgraph_hop": "2",
            "no_think_mode": "是",
            "synonym_merge_enable": "否",
            "disambiguation_enable": "是",
        }
        current = {
            "kds_id": "kb-1",
            "is_exist_graph": True,
            "graph_config": json.dumps(current_graph, ensure_ascii=False),
        }
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": {
                    "llm_model_name": "gpt-4o",
                    "retrieve_subgraph_hop": 3,
                    "no_think_mode": False,
                }},
            )

        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        payload = mock_update.call_args.args[3]
        # AIDP merges graph_config server-side, so only the edited fields are
        # sent; resending stored ones can make AIDP reject the PATCH.
        assert payload["graph_config"] == json.dumps(
            {
                "llm_model_name": "gpt-4o",
                "retrieve_subgraph_hop": "3",
                "no_think_mode": "否",
            },
            ensure_ascii=False,
        )
        # AIDP requires is_exist_graph=true alongside any graph_config edit.
        assert payload["is_exist_graph"] is True

    def test_update_forwards_graph_disable(self):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        current = {"kds_id": "kb-1", "is_exist_graph": True}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"is_exist_graph": False},
            )

        assert response.status_code == HTTPStatus.OK
        mock_update.assert_called_once()
        assert mock_update.call_args.args[3] == {"is_exist_graph": False}

    def test_update_rejects_graph_reenable(self):
        from ext_components.aidp.services import aidp_permission_service
        """The graph switch is one-way: re-enabling is permanently rejected."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        current = {"kds_id": "kb-1", "is_exist_graph": True}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"is_exist_graph": True},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "cannot be re-enabled" in response.json()["message"]
        mock_update.assert_not_called()

    def test_update_rejects_graph_config_when_graph_disabled(self):
        from ext_components.aidp.services import aidp_permission_service
        """Once the graph is off its configuration is locked for updates."""
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        current = {"kds_id": "kb-1", "is_exist_graph": False}
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

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "graph settings are locked" in response.json()["message"]
        mock_update.assert_not_called()

    @pytest.mark.parametrize("graph_updates", [
        {"retrieve_subgraph_hop": 4},      # out of range
        {"retrieve_subgraph_hop": "2"},    # string instead of int
        {"retrieve_subgraph_hop": True},   # bool is an int subclass
        {"llm_model_name": "   "},         # blank model name
        {"no_think_mode": "是"},           # string instead of bool
        {"domain": "通用"},                # non-editable graph field
    ])
    def test_update_rejects_invalid_graph_values(self, graph_updates):
        from ext_components.aidp.services import aidp_permission_service
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        current = {"kds_id": "kb-1", "is_exist_graph": True, "graph_config": "{}"}
        with patch.object(aidp_permission_service, "require_permission",
                          return_value=MagicMock(permission="EDIT")), \
             patch.object(aidp_mgmt_app, "_load_cached_kb_detail",
                          return_value=current), \
             patch.object(aidp_mgmt_app, "update_aidp_kb_impl",
                          return_value={"ok": True}) as mock_update:
            response = client.put(
                "/aidp-mgmt/knowledge-bases/kb-1",
                headers=_bearer(),
                json={"graph_config": graph_updates},
            )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        mock_update.assert_not_called()


class TestNormalizeKbConfigFields:
    """_normalize_kb_config_fields - kms_config_str merge and alias mapping."""

    def test_merges_kms_config_str_and_maps_topk(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "kds_id": "kb-1",
            "kms_config_str": (
                '{"chunk_mode": 1, "embedding_model": "bge-m3", '
                '"top_k": 5, "similarity": 0.6, "chunk_token_num": 512}'
            ),
            "caption_enable": 1,
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["chunk_mode"] == 1
        assert out["embedding_model"] == "bge-m3"
        assert out["chunk_token_num"] == 512
        assert out["topk"] == 5
        assert out["similarity"] == 0.6
        assert out["is_multimodal"] is True

    def test_top_level_values_win_and_bad_json_is_tolerated(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "topk": 7,
            "is_multimodal": False,
            "kms_config_str": "not valid json",
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["topk"] == 7
        assert out["is_multimodal"] is False
        assert out["kms_config_str"] == "not valid json"

    def test_non_dict_detail_passes_through(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._normalize_kb_config_fields(None) is None
        assert aidp_mgmt_app._normalize_kb_config_fields("x") == "x"

    def test_normalizes_graph_config_flags_and_lifts_llm_model(self):
        """AIDP serializes graph toggles as 是/否 and the hop as a string; the
        detail view expects native booleans, an int hop and a top-level LLM."""
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "graph_config": json.dumps({
                "llm_model_name": "qwen-max",
                "retrieve_subgraph_hop": "2",
                "no_think_mode": "是",
                "synonym_merge_enable": "否",
                "disambiguation_enable": "是",
            }, ensure_ascii=False),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        graph = out["graph_config"]
        assert isinstance(graph, dict)
        assert graph["retrieve_subgraph_hop"] == 2
        assert graph["no_think_mode"] is True
        assert graph["synonym_merge_enable"] is False
        assert graph["disambiguation_enable"] is True
        assert out["llm_model_name"] == "qwen-max"

    def test_top_level_llm_model_wins_over_graph_config(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {
            "llm_model_name": "top-model",
            "graph_config": json.dumps(
                {"llm_model_name": "nested-model"}, ensure_ascii=False
            ),
        }
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["llm_model_name"] == "top-model"
        assert out["graph_config"]["llm_model_name"] == "nested-model"

    def test_bad_graph_config_string_is_tolerated(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        detail = {"graph_config": "not valid json"}
        out = aidp_mgmt_app._normalize_kb_config_fields(detail)
        assert out["graph_config"] == "not valid json"
        assert "llm_model_name" not in out


# ---------------------------------------------------------------------------
# Coverage completion: tag cleanup delegation, doc-history channel helpers,
# graph-config degraded storage, response-shape guards and normalization
# edge branches
# ---------------------------------------------------------------------------


def test_cleanup_document_assignments_delegates_to_tag_management(monkeypatch):
    """The delete flow keeps document assignment usage in sync."""

    from management.services.tag import library as tag_library

    sentinel = MagicMock()
    monkeypatch.setattr(tag_library, "TagManagementService", sentinel)

    aidp_mgmt_app._cleanup_document_assignments_for_deleted_knowledge_base(
        "tenant-1", "kb-9", "user-1"
    )

    sentinel.cleanup_document_assignments_for_knowledge_base.assert_called_once_with(
        "tenant-1", "aidp", "kb-9", "user-1"
    )


class TestHistoryFallbackLogging:
    """The history fallback is reported once per knowledge base."""

    def test_warns_once_then_degrades_to_debug(self, caplog):
        from ext_components.aidp.apps import aidp_mgmt_app

        caplog.set_level(logging.DEBUG)
        aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-fb")
        try:
            aidp_mgmt_app._log_history_fallback("kb-fb", "reason-one")
            aidp_mgmt_app._log_history_fallback("kb-fb", "reason-two")
        finally:
            aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-fb")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(warnings) == 1
        assert "kb-fb" in warnings[0].getMessage()
        assert "reason-one" in warnings[0].getMessage()
        assert len(debugs) == 1
        assert "reason-two" in debugs[0].getMessage()


class TestResolveDocHistoryChannel:
    """Channel resolution feeds the upload-task history endpoint."""

    def test_returns_the_channel_selected_for_the_knowledge_base(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        channels = [{"fs_id": "fs-1", "src_dir": "/aidp/knowledge/kb-1"}]
        with patch.object(aidp_mgmt_app, "get_cached_aidp_channels",
                          return_value=channels) as mock_cache, \
             patch.object(aidp_mgmt_app, "select_aidp_channel",
                          return_value=channels[0]) as mock_select:
            channel = aidp_mgmt_app._resolve_doc_history_channel(
                SERVER_URL, API_KEY, "kb-1"
            )

        assert channel == channels[0]
        assert mock_cache.call_args.kwargs["kds_id"] == "kb-1"
        assert mock_select.call_args.args == (channels, "kb-1")

    def test_returns_none_and_reports_channel_shape_when_no_channel_matches(
        self, caplog
    ):
        from ext_components.aidp.apps import aidp_mgmt_app

        caplog.set_level(logging.WARNING)
        aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-noch")
        try:
            with patch.object(aidp_mgmt_app, "get_cached_aidp_channels",
                              return_value=[{"name": "channel-a"}]), \
                 patch.object(aidp_mgmt_app, "select_aidp_channel",
                              return_value=None):
                channel = aidp_mgmt_app._resolve_doc_history_channel(
                    SERVER_URL, API_KEY, "kb-noch"
                )
        finally:
            aidp_mgmt_app._HISTORY_FALLBACK_REPORTED.discard("kb-noch")

        assert channel is None
        message = caplog.records[-1].getMessage()
        assert "kb-noch" in message
        # The reported reason must make the channel payload shape visible.
        assert "'name'" in message


