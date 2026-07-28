import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest


PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
MODULE_PATH = os.path.join(PROJECT_ROOT, "sdk", "nexent", "core", "ext_components", "aidp", "aidp_search_tool.py")


@pytest.fixture
def aidp_module():
    original_modules = {}

    def register_module(name: str, module: ModuleType):
        if name in sys.modules:
            original_modules[name] = sys.modules[name]
        sys.modules[name] = module

    sdk_pkg = ModuleType("sdk")
    sdk_pkg.__path__ = []
    register_module("sdk", sdk_pkg)

    nexent_pkg = ModuleType("sdk.nexent")
    nexent_pkg.__path__ = []
    register_module("sdk.nexent", nexent_pkg)

    core_pkg = ModuleType("sdk.nexent.core")
    core_pkg.__path__ = []
    register_module("sdk.nexent.core", core_pkg)

    tools_pkg = ModuleType("sdk.nexent.core.tools")
    tools_pkg.__path__ = [os.path.dirname(MODULE_PATH)]
    register_module("sdk.nexent.core.tools", tools_pkg)

    utils_pkg = ModuleType("sdk.nexent.core.utils")
    utils_pkg.__path__ = [os.path.join(PROJECT_ROOT, "sdk", "nexent", "core", "utils")]
    register_module("sdk.nexent.core.utils", utils_pkg)

    sdk_utils_pkg = ModuleType("sdk.nexent.utils")
    sdk_utils_pkg.__path__ = [os.path.join(PROJECT_ROOT, "sdk", "nexent", "utils")]
    register_module("sdk.nexent.utils", sdk_utils_pkg)

    smolagents_pkg = ModuleType("smolagents")
    smolagents_pkg.__path__ = []
    register_module("smolagents", smolagents_pkg)

    smolagents_tools_mod = ModuleType("smolagents.tools")

    class DummyTool:
        def __init__(self, *args, **kwargs):
            # Intentionally empty: stand-in for smolagents Tool that skips
            # validation in unit tests.
            return

    smolagents_tools_mod.Tool = DummyTool
    register_module("smolagents.tools", smolagents_tools_mod)

    observer_spec = importlib.util.spec_from_file_location(
        "sdk.nexent.core.utils.observer",
        os.path.join(PROJECT_ROOT, "sdk", "nexent", "core", "utils", "observer.py"),
    )
    observer_module = importlib.util.module_from_spec(observer_spec)
    register_module("sdk.nexent.core.utils.observer", observer_module)
    observer_spec.loader.exec_module(observer_module)

    message_spec = importlib.util.spec_from_file_location(
        "sdk.nexent.core.utils.tools_common_message",
        os.path.join(PROJECT_ROOT, "sdk", "nexent", "core", "utils", "tools_common_message.py"),
    )
    message_module = importlib.util.module_from_spec(message_spec)
    register_module("sdk.nexent.core.utils.tools_common_message", message_module)
    message_spec.loader.exec_module(message_module)

    http_client_mod = ModuleType("sdk.nexent.utils.http_client_manager")
    http_client_mod.http_client_manager = MagicMock()
    register_module("sdk.nexent.utils.http_client_manager", http_client_mod)

    module_name = "sdk.nexent.core.ext_components.aidp.aidp_search_tool"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.ext_components.aidp"
    register_module(module_name, module)
    spec.loader.exec_module(module)

    try:
        yield module
    finally:
        for name in [
            module_name,
            "sdk.nexent.utils.http_client_manager",
            "sdk.nexent.core.utils.tools_common_message",
            "sdk.nexent.core.utils.observer",
            "smolagents.tools",
            "smolagents",
            "sdk.nexent.utils",
            "sdk.nexent.core.utils",
            "sdk.nexent.core.tools",
            "sdk.nexent.core",
            "sdk.nexent",
            "sdk",
        ]:
            if name in original_modules:
                sys.modules[name] = original_modules[name]
            else:
                sys.modules.pop(name, None)


@pytest.fixture
def mock_observer(aidp_module):
    observer = MagicMock(spec=aidp_module.MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def aidp_tool(aidp_module, mock_observer):
    mock_client = MagicMock()
    aidp_module.http_client_manager.get_sync_client.return_value = mock_client
    tool = aidp_module.AidpSearchTool(
        server_url="https://aidp.example.com/",
        api_key="jwt-token",
        tenant_id="aidp",
        kds_list='["kb1", "kb2"]',
        search_method="hybrid_search",
        reranking_enable=True,
        reranking_mode="high_accuracy",
        rewrite_enable=True,
        related_search_enable=True,
        score_threshold=0.7,
        top_k=2,
        multi_modal=True,
        observer=mock_observer,
    )
    tool._mock_http_client = mock_client
    return tool


def _build_aidp_response(records=None):
    if records is None:
        records = [
            {
                "id": "chunk-1",
                "chunk_type": "text",
                "title": "Text Doc",
                "text": "First result",
                "file_url": "https://aidp.example.com/files/1",
                "score": 0.95,
                "pages": [1],
                "metadata": {"source": "doc-1"},
            },
            {
                "id": "chunk-2",
                "chunk_type": "image",
                "title": "Image Doc",
                "text": "Image result",
                "file_url": "https://aidp.example.com/files/2.png",
                "score": 0.88,
                "pages": [2],
                "metadata": {"source": "doc-2"},
            },
        ]
    return {"result": records}


class TestAidpSearchToolInit:
    def test_init_success(self, aidp_module, mock_observer):
        mock_client = MagicMock()
        aidp_module.http_client_manager.get_sync_client.return_value = mock_client

        tool = aidp_module.AidpSearchTool(
                server_url="https://aidp.example.com/",
                api_key="jwt-token",
                tenant_id="aidp",
                kds_list='["kb1", "kb2"]',
                search_method="vector_search",
                reranking_enable=True,
                reranking_mode="high_accuracy",
                rewrite_enable=True,
                related_search_enable=True,
                score_threshold=1.5,
                top_k=200,
                multi_modal=True,
                observer=mock_observer,
            )

        assert tool.base_url == "https://aidp.example.com"
        assert tool.api_key == "jwt-token"
        assert tool.kds_list == ["kb1", "kb2"]
        assert tool.search_method == "vector_search"
        assert tool.reranking_enable is True
        assert tool.reranking_mode == "high_accuracy"
        assert tool.rewrite_enable is True
        assert tool.related_search_enable is True
        assert tool.score_threshold == pytest.approx(1.0)
        assert tool.top_k == 100
        assert tool.multi_modal is True
        assert tool.observer == mock_observer

    @pytest.mark.parametrize(
        "server_url,api_key,kds_list,expected_error",
        [
            ("", "jwt-token", '["kb1"]', "server_url is required and must be a non-empty string"),
            ("https://aidp.example.com", "", '["kb1"]', "api_key is required and must be a non-empty string"),
            ("https://aidp.example.com", "jwt-token", "[]", "kds_list must be a list of 1-10 knowledge base IDs"),
        ],
    )
    def test_init_invalid_required_values(
        self,
        server_url,
        api_key,
        kds_list,
        expected_error,
        mock_observer,
        aidp_module,
    ):
        with pytest.raises(ValueError) as exc_info:
            aidp_module.AidpSearchTool(
                server_url=server_url,
                api_key=api_key,
                tenant_id="aidp",
                kds_list=kds_list,
                observer=mock_observer,
            )

        assert expected_error in str(exc_info.value)

    def test_init_invalid_json_kds_list(self, aidp_module, mock_observer):
        with pytest.raises(ValueError) as exc_info:
            aidp_module.AidpSearchTool(
                server_url="https://aidp.example.com",
                api_key="jwt-token",
                tenant_id="aidp",
                kds_list="not-json",
                observer=mock_observer,
            )

        assert "kds_list must be a valid JSON array" in str(exc_info.value)

    def test_init_invalid_modes_fall_back(self, aidp_module, mock_observer):
        mock_client = MagicMock()
        aidp_module.http_client_manager.get_sync_client.return_value = mock_client

        tool = aidp_module.AidpSearchTool(
                server_url="https://aidp.example.com",
                api_key="jwt-token",
                tenant_id="aidp",
                kds_list='["kb1"]',
                search_method="bad-method",
                reranking_enable=True,
                reranking_mode="bad-mode",
                rewrite_enable=False,
                related_search_enable=False,
                score_threshold=0.0,
                top_k=10,
                multi_modal=True,
                observer=mock_observer,
            )

        assert tool.search_method == "hybrid_search"
        assert tool.reranking_mode == "performance"


class TestAidpSearchToolForward:
    def test_forward_success_uses_bearer_and_returns_results(
        self,
        aidp_tool,
        mock_observer,
        aidp_module,
    ):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = _build_aidp_response()
        aidp_tool._mock_http_client.post.return_value = mock_response

        result = aidp_tool.forward("find images")

        aidp_tool._mock_http_client.post.assert_called_once_with(
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer jwt-token",
            },
            json={
                "query": "find images",
                "kds_list": ["kb1", "kb2"],
                "search_method": "hybrid_search",
                "reranking_enable": True,
                "rewrite_enable": True,
                "related_search_enable": True,
                "score_threshold": 0.7,
                "top_k": 2,
                "multi_modal": True,
                "reranking_mode": "high_accuracy",
            },
        )

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["title"] == "Text Doc"
        assert parsed[1]["title"] == "Image Doc"
        assert aidp_tool.record_ops == 3

        assert mock_observer.add_message.call_count == 3
        assert mock_observer.add_message.call_args_list[0].args[1] == aidp_module.ProcessType.CARD
        assert mock_observer.add_message.call_args_list[1].args[1] == aidp_module.ProcessType.SEARCH_CONTENT
        assert mock_observer.add_message.call_args_list[2].args[1] == aidp_module.ProcessType.PICTURE_WEB
        assert "https://aidp.example.com/files/2.png" in mock_observer.add_message.call_args_list[2].args[2]

    def test_forward_without_image_does_not_emit_picture_message(
        self,
        aidp_tool,
        mock_observer,
        aidp_module,
    ):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = _build_aidp_response(
            records=[
                {
                    "id": "chunk-1",
                    "chunk_type": "text",
                    "title": "Only Text",
                    "text": "First result",
                    "file_url": "https://aidp.example.com/files/1",
                    "score": 0.95,
                    "pages": [1],
                    "metadata": {},
                }
            ]
        )
        aidp_tool._mock_http_client.post.return_value = mock_response

        result = aidp_tool.forward("text only")

        assert len(json.loads(result)) == 1
        process_types = [call.args[1] for call in mock_observer.add_message.call_args_list]
        assert aidp_module.ProcessType.PICTURE_WEB not in process_types

    def test_forward_empty_query_raises(self, aidp_tool):
        with pytest.raises(ValueError) as exc_info:
            aidp_tool.forward("   ")

        assert "query is required and must be a non-empty string" in str(exc_info.value)

    def test_forward_empty_result_raises_wrapped_exception(self, aidp_tool):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"result": []}
        aidp_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception) as exc_info:
            aidp_tool.forward("nothing")

        assert "AIDP search error: No results found!" in str(exc_info.value)

    def test_forward_http_error_raises_wrapped_exception(self, aidp_tool):
        aidp_tool._mock_http_client.post.side_effect = httpx.HTTPError("boom")

        with pytest.raises(Exception) as exc_info:
            aidp_tool.forward("query")

        assert "AIDP HTTP error: boom" in str(exc_info.value)

    def test_forward_invalid_response_shape_raises_wrapped_exception(self, aidp_tool):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"result": {"unexpected": True}}
        aidp_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception) as exc_info:
            aidp_tool.forward("query")

        assert "AIDP search error: Invalid AIDP response" in str(exc_info.value)


class TestAidpBuildImageUrl:
    """``_build_image_url`` joins the AIDP base URL, the KnowledgeBases path
    prefix, and the relative ``file_url`` returned by FusionSearch into a
    fully-qualified URL that the image proxy can GET with a Bearer token.
    """

    def test_relative_path_is_joined_under_knowledge_bases_prefix(self, aidp_tool):
        url = aidp_tool._build_image_url("kb-1/files/img.png")
        assert (
            url
            == "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/files/img.png"
        )

    def test_leading_slash_on_relative_path_is_stripped(self, aidp_tool):
        url = aidp_tool._build_image_url("/kb-1/files/img.png")
        assert (
            url
            == "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/files/img.png"
        )

    def test_already_absolute_http_url_is_returned_unchanged(self, aidp_tool):
        # Real AIDP currently returns relative paths, but if a future
        # version starts returning full URLs we must not double-prefix.
        url = aidp_tool._build_image_url("https://aidp.example.com/full/img.png")
        assert url == "https://aidp.example.com/full/img.png"

    def test_empty_file_url_returns_empty_string(self, aidp_tool):
        assert aidp_tool._build_image_url("") == ""

    def test_base_url_missing_trailing_slash_still_produces_valid_url(self, aidp_module, mock_observer):
        mock_client = MagicMock()
        aidp_module.http_client_manager.get_sync_client.return_value = mock_client
        tool = aidp_module.AidpSearchTool(
            server_url="https://aidp-no-slash.example.com",  # no trailing slash
            api_key="jwt-token",
            tenant_id="aidp",
            kds_list='["kb1"]',
            observer=mock_observer,
        )
        url = tool._build_image_url("kb-1/x.png")
        assert (
            url
            == "https://aidp-no-slash.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/x.png"
        )

    def test_forward_with_relative_file_url_emits_full_url_in_picture_channel(
        self, aidp_tool, mock_observer, aidp_module
    ):
        """End-to-end: a chunk whose file_url is a relative path must end up
        in the PICTURE_WEB message as the fully-qualified URL the image
        proxy can fetch."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = _build_aidp_response(
            records=[
                {
                    "id": "img-1",
                    "chunk_type": "image",
                    "title": "Relative image",
                    "text": "",
                    "file_url": "kb-1/data/picture.png",
                    "score": 0.88,
                    "pages": [1],
                    "metadata": {},
                }
            ]
        )
        aidp_tool._mock_http_client.post.return_value = mock_response

        aidp_tool.forward("image query")

        picture_call = mock_observer.add_message.call_args_list[-1]
        assert picture_call.args[1] == aidp_module.ProcessType.PICTURE_WEB
        assert (
            "https://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/data/picture.png"
            in picture_call.args[2]
        )


class TestAidpSearchToolWhitelist:
    """Tests for the v7.1 whitelist mechanism (_whitelist_installed /
    _allowed_kds_set / set_allowed_kds / _filter_by_whitelist) and its
    integration with forward().

    Three semantics of set_allowed_kds:
      * None  → whitelist NOT installed (legacy / SDK unit-test mode)
      * []    → whitelist installed, empty (block ALL KBs)
      * [ids] → whitelist installed, only these KBs allowed
    """

    # ------------------------------------------------------------------
    # A. set_allowed_kds three semantics
    # ------------------------------------------------------------------

    def test_set_allowed_kds_none_means_not_installed(self, aidp_tool):
        """set_allowed_kds(None) clears the whitelist and marks it as
        NOT installed, so _filter_by_whitelist becomes a no-op."""
        aidp_tool.set_allowed_kds(None)
        assert aidp_tool._whitelist_installed is False
        assert aidp_tool._allowed_kds_set == set()

    def test_set_allowed_kds_empty_list_means_installed_blocking_all(self, aidp_tool):
        """set_allowed_kds([]) installs an empty whitelist — semantically
        'user has access to nothing'."""
        aidp_tool.set_allowed_kds([])
        assert aidp_tool._whitelist_installed is True
        assert aidp_tool._allowed_kds_set == set()

    def test_set_allowed_kds_with_ids_installs_whitelist(self, aidp_tool):
        """set_allowed_kds(['kb-1', 'kb-2']) installs the whitelist with
        exactly those ids."""
        aidp_tool.set_allowed_kds(["kb-1", "kb-2"])
        assert aidp_tool._whitelist_installed is True
        assert aidp_tool._allowed_kds_set == {"kb-1", "kb-2"}

    def test_set_allowed_kds_coerces_ids_to_str(self, aidp_tool):
        """Numeric KB ids are coerced to strings."""
        aidp_tool.set_allowed_kds([123, 456])
        assert aidp_tool._allowed_kds_set == {"123", "456"}

    def test_set_allowed_kds_filters_falsy_values(self, aidp_tool):
        """Empty strings and None inside the list are silently dropped."""
        aidp_tool.set_allowed_kds(["kb-1", "", None, "kb-2"])
        assert aidp_tool._allowed_kds_set == {"kb-1", "kb-2"}

    # ------------------------------------------------------------------
    # B. _filter_by_whitelist behaviour
    # ------------------------------------------------------------------

    def test_filter_noop_when_whitelist_not_installed(self, aidp_tool):
        """When the whitelist was never installed, every KB passes through."""
        # Default state: _whitelist_installed is False
        result = aidp_tool._filter_by_whitelist(["any-kb", "other-kb"])
        assert result == ["any-kb", "other-kb"]

    def test_filter_blocks_all_when_whitelist_empty(self, aidp_tool):
        """Installed empty whitelist blocks every KB."""
        aidp_tool.set_allowed_kds([])
        result = aidp_tool._filter_by_whitelist(["kb-1", "kb-2"])
        assert result == []

    def test_filter_partial_match_preserves_order(self, aidp_tool):
        """Only whitelisted ids survive, original order is preserved."""
        aidp_tool.set_allowed_kds(["kb-1", "kb-2"])
        result = aidp_tool._filter_by_whitelist(["kb-1", "kb-3", "kb-2"])
        assert result == ["kb-1", "kb-2"]

    def test_filter_no_match_returns_empty(self, aidp_tool):
        """When none of the input ids are in the whitelist, result is empty."""
        aidp_tool.set_allowed_kds(["kb-1", "kb-2"])
        result = aidp_tool._filter_by_whitelist(["kb-99", "kb-100"])
        assert result == []

    def test_filter_exact_match_returns_all(self, aidp_tool):
        """When every input id is whitelisted, all pass through in order."""
        aidp_tool.set_allowed_kds(["kb-1", "kb-2", "kb-3"])
        result = aidp_tool._filter_by_whitelist(["kb-2", "kb-1"])
        assert result == ["kb-2", "kb-1"]

    def test_filter_empty_input_returns_empty(self, aidp_tool):
        """Empty input list yields empty output regardless of whitelist state."""
        aidp_tool.set_allowed_kds(["kb-1"])
        assert aidp_tool._filter_by_whitelist([]) == []

    def test_filter_returns_shallow_copy(self, aidp_tool):
        """_filter_by_whitelist must not return the original list reference
        when whitelist is not installed (it calls list(kds))."""
        input_list = ["kb-1"]
        result = aidp_tool._filter_by_whitelist(input_list)
        assert result == input_list
        assert result is not input_list

    # ------------------------------------------------------------------
    # C. forward() with empty whitelist — block before HTTP call
    # ------------------------------------------------------------------

    def test_forward_empty_whitelist_raises_without_http_call(self, aidp_tool):
        """When the whitelist is installed but empty, forward raises
        AidpSearchError and never touches the AIDP API."""
        aidp_tool.set_allowed_kds([])

        with pytest.raises(Exception) as exc_info:
            aidp_tool.forward("some query")

        assert "No accessible knowledge base" in str(exc_info.value)
        aidp_tool._mock_http_client.post.assert_not_called()

    def test_forward_configured_kds_blocked_by_empty_whitelist(self, aidp_tool):
        """Even the tool's own configured kds_list is blocked when the
        whitelist is empty."""
        # aidp_tool was created with kds_list=["kb1", "kb2"]
        aidp_tool.set_allowed_kds([])

        with pytest.raises(Exception) as exc_info:
            aidp_tool.forward("query")

        assert "No accessible knowledge base" in str(exc_info.value)
        aidp_tool._mock_http_client.post.assert_not_called()

    # ------------------------------------------------------------------
    # D. forward() with privilege-escalation attempt
    # ------------------------------------------------------------------

    def test_forward_strips_unauthorized_kds_from_user_input(self, aidp_tool):
        """When the LLM passes kds_list that includes a non-whitelisted KB,
        that KB is silently removed and the query proceeds with allowed ones."""
        aidp_tool.set_allowed_kds(["kb-1", "kb2"])

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = _build_aidp_response(
            records=[
                {
                    "id": "chunk-1",
                    "chunk_type": "text",
                    "title": "Doc",
                    "text": "result",
                    "file_url": "",
                    "score": 0.9,
                    "pages": [],
                    "metadata": {},
                }
            ]
        )
        aidp_tool._mock_http_client.post.return_value = mock_response

        # "kb-99" is not whitelisted and must be stripped
        aidp_tool.forward("query", kds_list=["kb-1", "kb-99", "kb2"])

        # Verify the HTTP call used only whitelisted KBs
        call_kwargs = aidp_tool._mock_http_client.post.call_args.kwargs
        sent_payload = call_kwargs["json"]
        assert "kb-99" not in sent_payload["kds_list"]
        assert "kb-1" in sent_payload["kds_list"]
        assert "kb2" in sent_payload["kds_list"]

    def test_forward_all_kds_filtered_raises_error(self, aidp_tool):
        """When every user-supplied KB is stripped by the whitelist,
        forward raises AidpSearchError instead of calling AIDP."""
        aidp_tool.set_allowed_kds(["kb-allowed"])

        with pytest.raises(Exception) as exc_info:
            aidp_tool.forward("query", kds_list=["kb-bad1", "kb-bad2"])

        assert "No accessible knowledge base" in str(exc_info.value)
        aidp_tool._mock_http_client.post.assert_not_called()

    def test_forward_no_whitelist_passes_all_kds(self, aidp_tool):
        """When set_allowed_kds was never called, all configured KBs pass."""
        # Default: _whitelist_installed is False
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = _build_aidp_response()
        aidp_tool._mock_http_client.post.return_value = mock_response

        aidp_tool.forward("query")

        call_kwargs = aidp_tool._mock_http_client.post.call_args.kwargs
        sent_payload = call_kwargs["json"]
        assert sent_payload["kds_list"] == ["kb1", "kb2"]

    # ------------------------------------------------------------------
    # E. State switching
    # ------------------------------------------------------------------

    def test_state_transition_install_uninstall_reinstall(self, aidp_tool):
        """Install → uninstall → reinstall: verify the two flag fields
        track correctly through each transition."""
        # Step 1: install with ids
        aidp_tool.set_allowed_kds(["kb-1"])
        assert aidp_tool._whitelist_installed is True
        assert aidp_tool._allowed_kds_set == {"kb-1"}

        # Step 2: uninstall (None)
        aidp_tool.set_allowed_kds(None)
        assert aidp_tool._whitelist_installed is False
        assert aidp_tool._allowed_kds_set == set()

        # Step 3: reinstall as empty
        aidp_tool.set_allowed_kds([])
        assert aidp_tool._whitelist_installed is True
        assert aidp_tool._allowed_kds_set == set()

    def test_state_transition_reinstall_with_different_ids(self, aidp_tool):
        """Re-installing with a different set replaces the previous one."""
        aidp_tool.set_allowed_kds(["kb-1", "kb-2"])
        assert aidp_tool._allowed_kds_set == {"kb-1", "kb-2"}

        aidp_tool.set_allowed_kds(["kb-3"])
        assert aidp_tool._allowed_kds_set == {"kb-3"}
        assert aidp_tool._whitelist_installed is True

    def test_filter_after_uninstall_becomes_noop(self, aidp_tool):
        """After uninstalling the whitelist, _filter_by_whitelist reverts
        to no-op behaviour."""
        aidp_tool.set_allowed_kds(["kb-1"])
        assert aidp_tool._filter_by_whitelist(["kb-99"]) == []

        aidp_tool.set_allowed_kds(None)
        assert aidp_tool._filter_by_whitelist(["kb-99"]) == ["kb-99"]


# ---------------------------------------------------------------------------
# _execute_request retry logic (502/503/504 transient retries)
# ---------------------------------------------------------------------------


class TestExecuteRequestRetry:
    """Covers the transient HTTP retry logic in _execute_request
    (502 / 503 / 504 with exponential backoff)."""

    def _make_response(self, status_code, json_data=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.reason_phrase = "Error"
        resp.request = httpx.Request("POST", "http://test")
        if json_data is not None:
            resp.json.return_value = json_data
            resp.raise_for_status.return_value = None
        else:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                message=f"{status_code}",
                request=resp.request,
                response=resp,
            )
        return resp

    def test_retry_503_then_success(self, aidp_tool, monkeypatch):
        """First call returns 503, second returns 200. Should retry and succeed."""
        resp_503 = self._make_response(503)
        resp_ok = self._make_response(200, json_data={"result": [{"id": "c1", "chunk_type": "text",
                                                                   "title": "", "text": "ok",
                                                                   "file_url": "", "score": 0.9,
                                                                   "pages": [], "metadata": {}}]})
        aidp_tool._mock_http_client.post.side_effect = [resp_503, resp_ok]
        monkeypatch.setattr(aidp_tool._mock_http_client, "__class__", MagicMock.__class__)

        # Skip actual sleep
        import time as _time
        monkeypatch.setattr(_time, "sleep", lambda s: None)

        records = aidp_tool._execute_request("query", ["kb1"])
        assert len(records) == 1
        assert aidp_tool._mock_http_client.post.call_count == 2

    def test_retry_503_all_attempts_exhausted_raises_503_specific(self, aidp_tool, monkeypatch):
        """All 3 attempts return 503. Should raise AidpSearchError with 503-specific message."""
        resp_503 = self._make_response(503)
        aidp_tool._mock_http_client.post.return_value = resp_503

        import time as _time
        monkeypatch.setattr(_time, "sleep", lambda s: None)

        with pytest.raises(Exception) as exc_info:
            aidp_tool._execute_request("query", ["kb1"])
        assert "temporarily unavailable" in str(exc_info.value).lower() or "503" in str(exc_info.value)
        assert aidp_tool._mock_http_client.post.call_count == 3

    def test_retry_502_all_attempts_exhausted_raises_generic(self, aidp_tool, monkeypatch):
        """All 3 attempts return 502. Should raise AidpSearchError with generic transient message."""
        resp_502 = self._make_response(502)
        aidp_tool._mock_http_client.post.return_value = resp_502

        import time as _time
        monkeypatch.setattr(_time, "sleep", lambda s: None)

        with pytest.raises(Exception) as exc_info:
            aidp_tool._execute_request("query", ["kb1"])
        assert "502" in str(exc_info.value)
        assert aidp_tool._mock_http_client.post.call_count == 3

    def test_no_retry_on_400(self, aidp_tool):
        """400 is not a retryable status. Should raise immediately after one call."""
        resp_400 = self._make_response(400)
        aidp_tool._mock_http_client.post.return_value = resp_400

        with pytest.raises(httpx.HTTPStatusError):
            aidp_tool._execute_request("query", ["kb1"])
        assert aidp_tool._mock_http_client.post.call_count == 1


# ---------------------------------------------------------------------------
# _resolve_field_default with FieldInfo
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Init with empty tenant_id (line 183)
# ---------------------------------------------------------------------------


class TestInitEmptyTenantId:
    def test_empty_tenant_id_raises(self, aidp_module, mock_observer):
        with pytest.raises(ValueError, match="tenant_id is required"):
            aidp_module.AidpSearchTool(
                server_url="https://aidp.example.com",
                api_key="jwt-token",
                tenant_id="",
                kds_list='["kb1"]',
                observer=mock_observer,
            )

    def test_non_string_tenant_id_raises(self, aidp_module, mock_observer):
        with pytest.raises(ValueError, match="tenant_id is required"):
            aidp_module.AidpSearchTool(
                server_url="https://aidp.example.com",
                api_key="jwt-token",
                tenant_id=123,
                kds_list='["kb1"]',
                observer=mock_observer,
            )


# ---------------------------------------------------------------------------
# forward() without observer (hits _emit_running_prompt and _emit_results
# early-return paths, lines 259, 319)
# ---------------------------------------------------------------------------


class TestForwardWithoutObserver:
    def test_forward_no_observer_succeeds(self, aidp_module):
        """Tool with observer=None exercises the early-return paths
        in _emit_running_prompt and _emit_results."""
        mock_client = MagicMock()
        aidp_module.http_client_manager.get_sync_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = _build_aidp_response(
            records=[
                {
                    "id": "chunk-1", "chunk_type": "text", "title": "Doc",
                    "text": "ok", "file_url": "", "score": 0.9,
                    "pages": [], "metadata": {},
                }
            ]
        )
        mock_client.post.return_value = mock_response

        tool = aidp_module.AidpSearchTool(
            server_url="https://aidp.example.com",
            api_key="jwt-token",
            tenant_id="aidp",
            kds_list='["kb1"]',
            observer=None,
        )
        tool._http_client = mock_client
        result = tool.forward("no observer query")
        parsed = json.loads(result)
        assert len(parsed) == 1


class TestResolveFieldDefault:
    """Covers _resolve_field_default when value is a FieldInfo instance."""

    def test_field_info_with_ellipsis_returns_fallback(self, aidp_module):
        from pydantic.fields import FieldInfo
        fi = FieldInfo()
        # Pydantic v2 uses PydanticUndefined for defaults, but the source
        # code checks ``value.default is ...``. Create a FieldInfo whose
        # .default is literally Ellipsis to exercise that branch.
        object.__setattr__(fi, "default", ...)
        result = aidp_module._resolve_field_default(fi, "fallback_value")
        assert result == "fallback_value"

    def test_field_info_with_explicit_default_returns_it(self, aidp_module):
        from pydantic.fields import FieldInfo
        fi = FieldInfo()
        object.__setattr__(fi, "default", "custom_default")
        result = aidp_module._resolve_field_default(fi, "fallback_value")
        assert result == "custom_default"

    def test_none_value_returns_fallback(self, aidp_module):
        assert aidp_module._resolve_field_default(None, 42) == 42

    def test_non_none_value_returns_it(self, aidp_module):
        assert aidp_module._resolve_field_default("hello", 42) == "hello"


# ---------------------------------------------------------------------------
# _parse_kds_list with non-string input (pre-parsed list)
# ---------------------------------------------------------------------------


class TestParseKdsListNonString:
    def test_list_input_bypasses_json_parse(self, aidp_module):
        result = aidp_module._parse_kds_list(["kb1", "kb2"])
        assert result == ["kb1", "kb2"]

    def test_too_many_kds_raises(self, aidp_module):
        with pytest.raises(ValueError, match="1-10"):
            aidp_module._parse_kds_list(["kb"] * 11)

    def test_empty_list_raises(self, aidp_module):
        with pytest.raises(ValueError, match="1-10"):
            aidp_module._parse_kds_list([])


# ---------------------------------------------------------------------------
# _build_retrieve_payload with reranking disabled
# ---------------------------------------------------------------------------


class TestBuildRetrievePayload:
    def test_reranking_disabled_omits_reranking_mode(self, aidp_module, mock_observer):
        mock_client = MagicMock()
        aidp_module.http_client_manager.get_sync_client.return_value = mock_client

        tool = aidp_module.AidpSearchTool(
            server_url="https://aidp.example.com",
            api_key="jwt-token",
            tenant_id="aidp",
            kds_list='["kb1"]',
            reranking_enable=False,
            observer=mock_observer,
        )
        payload = tool._build_retrieve_payload("q", ["kb1"])
        assert "reranking_mode" not in payload

    def test_reranking_enabled_includes_reranking_mode(self, aidp_tool):
        payload = aidp_tool._build_retrieve_payload("q", ["kb1"])
        assert payload["reranking_mode"] == "high_accuracy"
