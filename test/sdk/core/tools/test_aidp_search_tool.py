import importlib.util
import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
MODULE_PATH = os.path.join(PROJECT_ROOT, "sdk", "nexent", "core", "tools", "aidp_search_tool.py")


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

    module_name = "sdk.nexent.core.tools.aidp_search_tool"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.tools"
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
                kds_list=kds_list,
                observer=mock_observer,
            )

        assert expected_error in str(exc_info.value)

    def test_init_invalid_json_kds_list(self, aidp_module, mock_observer):
        with pytest.raises(ValueError) as exc_info:
            aidp_module.AidpSearchTool(
                server_url="https://aidp.example.com",
                api_key="jwt-token",
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
