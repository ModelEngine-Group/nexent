import json
import sys
import types
from typing import List
from unittest.mock import ANY, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies BEFORE any SDK imports.
# sdk/nexent/__init__.py triggers a full import chain (memory, models, etc.)
# that requires many third-party packages.  We mock the intermediate
# namespace packages so their __init__.py files are never executed.
# ---------------------------------------------------------------------------

# -- smolagents ---------------------------------------------------------------
class _MockTool:
    """A proper class that RAGFlowSearchTool can inherit from."""
    def __init__(self, *args, **kwargs):
        # No-op: smolagents.Tool.__init__ does setup that we don't need in tests.
        # RAGFlowSearchTool calls super().__init__() which must not fail.
        pass


_mock_smolagents = MagicMock()
_mock_smolagents_tools = types.ModuleType("smolagents.tools")
_mock_smolagents_tools.Tool = _MockTool
_mock_smolagents.tools = _mock_smolagents_tools
_mock_smolagents.memory = MagicMock()

# -- namespace package stubs --------------------------------------------------
_mock_sdk = types.ModuleType("sdk")
_mock_sdk_nexent = types.ModuleType("sdk.nexent")
_mock_sdk_nexent_core = types.ModuleType("sdk.nexent.core")
_mock_sdk_nexent_core_tools = types.ModuleType("sdk.nexent.core.tools")
_mock_sdk_nexent_core_utils = types.ModuleType("sdk.nexent.core.utils")
_mock_sdk_nexent_utils = types.ModuleType("sdk.nexent.utils")
_mock_nexent = types.ModuleType("nexent")
_mock_nexent_utils = types.ModuleType("nexent.utils")

# Set __path__ so Python treats these as namespace packages and can locate
# sub-modules underneath them.
SDK_SOURCE_ROOT = __import__("pathlib").Path(__file__).resolve().parents[4] / "sdk"
_mock_sdk.__path__ = [str(SDK_SOURCE_ROOT)]
_mock_sdk_nexent.__path__ = [str(SDK_SOURCE_ROOT / "nexent")]
_mock_sdk_nexent_core.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core")]
_mock_sdk_nexent_core_tools.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core" / "tools")]
_mock_sdk_nexent_core_utils.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core" / "utils")]
_mock_sdk_nexent_utils.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "utils")]

# -- http_client_manager stubs (both nexent.utils and sdk.nexent.utils) --------
_mock_nexent_utils_http = types.ModuleType("nexent.utils.http_client_manager")
_mock_nexent_utils_http.http_client_manager = MagicMock()
_mock_sdk_nexent_utils_http = types.ModuleType("sdk.nexent.utils.http_client_manager")
_mock_sdk_nexent_utils_http.http_client_manager = MagicMock()

# -- Register all mocks in sys.modules ----------------------------------------
_MODULE_MOCKS = {
    "smolagents": _mock_smolagents,
    "smolagents.tools": _mock_smolagents_tools,
    "smolagents.memory": _mock_smolagents.memory,
    "sdk": _mock_sdk,
    "sdk.nexent": _mock_sdk_nexent,
    "sdk.nexent.core": _mock_sdk_nexent_core,
    "sdk.nexent.core.tools": _mock_sdk_nexent_core_tools,
    "sdk.nexent.core.utils": _mock_sdk_nexent_core_utils,
    "sdk.nexent.utils": _mock_sdk_nexent_utils,
    "sdk.nexent.utils.http_client_manager": _mock_sdk_nexent_utils_http,
    "nexent": _mock_nexent,
    "nexent.utils": _mock_nexent_utils,
    "nexent.utils.http_client_manager": _mock_nexent_utils_http,
}
sys.modules.update(_MODULE_MOCKS)

# Now it is safe to import the module under test — the mocked namespace
# packages prevent __init__.py execution, and Python finds the real
# ragflow_search_tool.py via the __path__ on sdk.nexent.core.tools.
from sdk.nexent.core.tools.ragflow_search_tool import RAGFlowSearchTool, _resolve_default  # noqa: E402
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_observer():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def ragflow_tool(mock_observer: MessageObserver) -> RAGFlowSearchTool:
    with patch.object(
        RAGFlowSearchTool, "__init__", lambda self, **kw: None
    ):
        tool = RAGFlowSearchTool.__new__(RAGFlowSearchTool)
    # Manually set attributes without going through __init__
    tool.server_url = "http://localhost:9380"
    tool.api_key = "test_api_key"
    tool.dataset_ids = ["dataset1", "dataset2"]
    tool.top_k = 3
    tool.similarity_threshold = 0.2
    tool.vector_similarity_weight = 0.3
    tool.keyword = False
    tool.highlight = True
    tool.observer = mock_observer
    tool.record_ops = 1
    tool.running_prompt_zh = "RAGFlow知识库检索中..."
    tool.running_prompt_en = "Searching RAGFlow knowledge base..."
    tool.name = "ragflow_search"
    tool.tool_sign = "k"
    tool._http_client = MagicMock()
    tool._mock_http_client = tool._http_client
    return tool


def _build_search_response(chunks: List[dict] = None, total: int = None):
    """Build a RAGFlow API search response."""
    if chunks is None:
        chunks = [
            {
                "id": "chunk1",
                "content_with_weight": "test content 1",
                "docnm_kwd": "document1.txt",
                "important_kwd": ["keyword1", "keyword2"],
                "similarity": 0.9,
                "term_similarity": 0.85,
                "vector_similarity": 0.92,
                "doc_id": "doc1",
            },
            {
                "id": "chunk2",
                "content_ltks": "test content 2",
                "docnm_kwd": "document2.txt",
                "important_kwd": [],
                "similarity": 0.8,
                "term_similarity": 0.75,
                "vector_similarity": 0.82,
                "doc_id": "doc2",
            },
        ]
    return {
        "code": 0,
        "message": "Success",
        "data": {
            "chunks": chunks,
            "total": total if total is not None else len(chunks),
        },
    }


# ---------------------------------------------------------------------------
# _resolve_default
# ---------------------------------------------------------------------------

class TestResolveDefault:
    def test_resolve_default_returns_plain_value(self):
        assert _resolve_default("hello") == "hello"
        assert _resolve_default(42) == 42
        assert _resolve_default(None) is None
        assert _resolve_default(True) is True

    def test_resolve_default_returns_fieldinfo_default(self):
        from pydantic import Field
        field_info = Field(default="my_default", description="test")
        assert _resolve_default(field_info) == "my_default"


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestRAGFlowSearchToolInit:
    def test_init_success(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids='["ds1", "ds2"]',
                top_k=5,
                similarity_threshold=0.25,
                vector_similarity_weight=0.5,
                keyword=True,
                highlight=False,
                observer=mock_observer,
            )

        assert tool.server_url == "http://localhost:9380"
        assert tool.dataset_ids == ["ds1", "ds2"]
        assert tool.api_key == "test_key"
        assert tool.top_k == 5
        assert tool.similarity_threshold == pytest.approx(0.25)
        assert tool.vector_similarity_weight == pytest.approx(0.5)
        assert tool.keyword is True
        assert tool.highlight is False
        assert tool.observer is mock_observer
        assert tool.record_ops == 1
        assert tool.running_prompt_zh == "RAGFlow知识库检索中..."
        assert tool.running_prompt_en == "Searching RAGFlow knowledge base..."

    def test_init_server_url_strips_trailing_slash(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380/",
                api_key="test_key",
                dataset_ids='["ds1"]',
                observer=mock_observer,
            )
        assert tool.server_url == "http://localhost:9380"

    def test_init_single_dataset_id(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids='["single_dataset"]',
                observer=mock_observer,
            )
        assert tool.dataset_ids == ["single_dataset"]

    def test_init_json_string_array_multiple_dataset_ids(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids='["ds1", "ds2", "ds3"]',
                observer=mock_observer,
            )
        assert tool.dataset_ids == ["ds1", "ds2", "ds3"]

    @pytest.mark.parametrize("server_url,expected_error", [
        ("", "server_url is required and must be a non-empty string"),
        (None, "server_url is required and must be a non-empty string"),
    ])
    def test_init_invalid_server_url(self, server_url, expected_error, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            with pytest.raises(ValueError) as excinfo:
                RAGFlowSearchTool(
                    server_url=server_url,
                    api_key="test_key",
                    dataset_ids='["ds1"]',
                    observer=mock_observer,
                )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("api_key,expected_error", [
        ("", "api_key is required and must be a non-empty string"),
        (None, "api_key is required and must be a non-empty string"),
    ])
    def test_init_invalid_api_key(self, api_key, expected_error, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            with pytest.raises(ValueError) as excinfo:
                RAGFlowSearchTool(
                    server_url="http://localhost:9380",
                    api_key=api_key,
                    dataset_ids='["ds1"]',
                    observer=mock_observer,
                )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("dataset_ids,expected_error", [
        ([], "dataset_ids is required and must be a non-empty JSON string array or list"),
        ("", "dataset_ids is required and must be a non-empty JSON string array or list"),
        (None, "dataset_ids is required and must be a non-empty JSON string array or list"),
    ])
    def test_init_invalid_dataset_ids(self, dataset_ids, expected_error, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            with pytest.raises(ValueError) as excinfo:
                RAGFlowSearchTool(
                    server_url="http://localhost:9380",
                    api_key="test_key",
                    dataset_ids=dataset_ids,
                    observer=mock_observer,
                )
        assert expected_error in str(excinfo.value)

    def test_init_dataset_ids_empty_json_array_string(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            with pytest.raises(ValueError) as excinfo:
                RAGFlowSearchTool(
                    server_url="http://localhost:9380",
                    api_key="test_key",
                    dataset_ids="[]",
                    observer=mock_observer,
                )
        assert "dataset_ids must be a non-empty array of strings" in str(excinfo.value)

    def test_init_dataset_ids_as_list(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids=["ds1", "ds2", "ds3"],
                observer=mock_observer,
            )
        assert tool.dataset_ids == ["ds1", "ds2", "ds3"]

    def test_init_dataset_ids_as_list_single_item(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids=["single_dataset"],
                observer=mock_observer,
            )
        assert tool.dataset_ids == ["single_dataset"]

    def test_init_dataset_ids_as_list_with_numeric_ids(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids=[123, 456, 789],
                observer=mock_observer,
            )
        assert tool.dataset_ids == ["123", "456", "789"]
        assert all(isinstance(ds_id, str) for ds_id in tool.dataset_ids)

    @pytest.mark.parametrize("invalid_json,expected_error_contains", [
        ("invalid_json", "dataset_ids must be a valid JSON string array or list"),
        ("{key: value}", "dataset_ids must be a valid JSON string array or list"),
        ("{'key': 'value'}", "dataset_ids must be a valid JSON string array or list"),
        ("123", "dataset_ids must be a non-empty array of strings"),
    ])
    def test_init_invalid_json_format(self, invalid_json, expected_error_contains, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            with pytest.raises(ValueError) as excinfo:
                RAGFlowSearchTool(
                    server_url="http://localhost:9380",
                    api_key="test_key",
                    dataset_ids=invalid_json,
                    observer=mock_observer,
                )
        assert expected_error_contains in str(excinfo.value)

    def test_init_dataset_ids_with_malformed_json_array(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            with pytest.raises(ValueError) as excinfo:
                RAGFlowSearchTool(
                    server_url="http://localhost:9380",
                    api_key="test_key",
                    dataset_ids='["ds1", "ds2"',
                    observer=mock_observer,
                )
        assert "dataset_ids must be a valid JSON string array or list" in str(excinfo.value)

    def test_init_dataset_ids_json_string_with_non_string_elements(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids='["ds1", 123, true, null]',
                observer=mock_observer,
            )
        assert tool.dataset_ids == ["ds1", "123", "True", "None"]
        assert all(isinstance(ds_id, str) for ds_id in tool.dataset_ids)

    def test_init_default_values(self, mock_observer: MessageObserver):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids='["ds1"]',
                observer=mock_observer,
            )
        assert tool.top_k == 3
        assert tool.similarity_threshold == pytest.approx(0.2)
        assert tool.vector_similarity_weight == pytest.approx(0.3)
        assert tool.keyword is False
        assert tool.highlight is True

    def test_init_observer_none(self):
        with patch("sdk.nexent.core.tools.ragflow_search_tool.http_client_manager") as mock_mgr:
            mock_mgr.get_sync_client.return_value = MagicMock()
            tool = RAGFlowSearchTool(
                server_url="http://localhost:9380",
                api_key="test_key",
                dataset_ids='["ds1"]',
                observer=None,
            )
        assert tool.observer is None


# ---------------------------------------------------------------------------
# _resolve_effective_dataset_ids
# ---------------------------------------------------------------------------

class TestResolveEffectiveDatasetIds:
    def test_returns_configured_when_empty_string(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids("")
        assert result == ["dataset1", "dataset2"]

    def test_returns_configured_when_none(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids(None)
        assert result == ["dataset1", "dataset2"]

    def test_returns_configured_when_empty_list(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids([])
        assert result == ["dataset1", "dataset2"]

    def test_override_with_json_string(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids('["ds3", "ds4"]')
        assert result == ["ds3", "ds4"]

    def test_override_with_list(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids(["ds5", "ds6"])
        assert result == ["ds5", "ds6"]

    def test_override_with_single_non_json_string(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids("single_dataset")
        assert result == ["single_dataset"]

    def test_non_bracket_string_treated_as_single_dataset(self, ragflow_tool: RAGFlowSearchTool):
        """A string that doesn't start with '[' is treated as a single dataset ID."""
        result = ragflow_tool._resolve_effective_dataset_ids("{invalid}")
        assert result == ["{invalid}"]

    def test_fallback_on_invalid_json_array(self, ragflow_tool: RAGFlowSearchTool):
        """A string starting with '[' but containing invalid JSON falls back to configured datasets."""
        result = ragflow_tool._resolve_effective_dataset_ids("[invalid]")
        assert result == ["dataset1", "dataset2"]

    def test_list_items_converted_to_strings(self, ragflow_tool: RAGFlowSearchTool):
        result = ragflow_tool._resolve_effective_dataset_ids([123, 456])
        assert result == ["123", "456"]


# ---------------------------------------------------------------------------
# _parse_doc_ids
# ---------------------------------------------------------------------------

class TestParseDocIds:
    def test_returns_empty_for_empty_string(self):
        assert RAGFlowSearchTool._parse_doc_ids("") == []

    def test_returns_empty_for_none(self):
        assert RAGFlowSearchTool._parse_doc_ids(None) == []

    def test_returns_empty_for_empty_list(self):
        assert RAGFlowSearchTool._parse_doc_ids([]) == []

    def test_single_doc_id(self):
        assert RAGFlowSearchTool._parse_doc_ids("doc1") == ["doc1"]

    def test_json_array_string(self):
        result = RAGFlowSearchTool._parse_doc_ids('["doc1", "doc2"]')
        assert result == ["doc1", "doc2"]

    def test_native_list(self):
        result = RAGFlowSearchTool._parse_doc_ids(["doc1", "doc2"])
        assert result == ["doc1", "doc2"]

    def test_invalid_json_array_fallback(self):
        """A string starting with '[' but containing invalid JSON returns empty list."""
        result = RAGFlowSearchTool._parse_doc_ids("[bad json]")
        assert result == []

    def test_non_bracket_string_treated_as_single_doc_id(self):
        """A string that doesn't start with '[' is treated as a single document ID."""
        result = RAGFlowSearchTool._parse_doc_ids("{bad json}")
        assert result == ["{bad json}"]

    def test_strips_whitespace(self):
        assert RAGFlowSearchTool._parse_doc_ids("  doc1  ") == ["doc1"]

    def test_native_list_converts_to_strings(self):
        result = RAGFlowSearchTool._parse_doc_ids([111, 222])
        assert result == ["111", "222"]


# ---------------------------------------------------------------------------
# _build_result_messages
# ---------------------------------------------------------------------------

class TestBuildResultMessages:
    def test_build_from_chunks(self, ragflow_tool: RAGFlowSearchTool):
        chunks = [
            {
                "content_with_weight": "content A",
                "docnm_kwd": "doc_a.txt",
                "important_kwd": ["kw1", "kw2"],
                "similarity": 0.95,
                "term_similarity": 0.90,
                "vector_similarity": 0.97,
            },
            {
                "content_ltks": "content B",
                "docnm_kwd": "doc_b.txt",
                "important_kwd": [],
                "similarity": 0.7,
                "term_similarity": 0.65,
                "vector_similarity": 0.72,
            },
        ]
        json_msgs, model_msgs = ragflow_tool._build_result_messages(chunks)

        assert len(json_msgs) == 2
        assert len(model_msgs) == 2

        # First chunk
        assert json_msgs[0]["title"] == "doc_a.txt [kw1, kw2]"
        assert json_msgs[0]["text"] == "content A"
        assert json_msgs[0]["source_type"] == "ragflow"
        assert json_msgs[0]["filename"] == "doc_a.txt"
        assert json_msgs[0]["score"] == "0.95"
        assert json_msgs[0]["score_details"]["term_similarity"] == pytest.approx(0.90)
        assert json_msgs[0]["score_details"]["vector_similarity"] == pytest.approx(0.97)
        assert json_msgs[0]["cite_index"] == ragflow_tool.record_ops + 0
        assert json_msgs[0]["search_type"] == "ragflow_search"
        assert json_msgs[0]["tool_sign"] == "k"

        # Second chunk
        assert json_msgs[1]["title"] == "doc_b.txt"
        assert json_msgs[1]["text"] == "content B"
        assert json_msgs[1]["score"] == "0.7"
        assert json_msgs[1]["cite_index"] == ragflow_tool.record_ops + 1

        # Model dict format
        assert model_msgs[0]["index"] == f"k{ragflow_tool.record_ops + 0}"

    def test_build_uses_content_ltks_as_fallback(self, ragflow_tool: RAGFlowSearchTool):
        chunks = [
            {
                "content_with_weight": "",
                "content_ltks": "fallback content",
                "docnm_kwd": "doc.txt",
                "important_kwd": [],
                "similarity": 0.5,
            }
        ]
        json_msgs, _model_msgs = ragflow_tool._build_result_messages(chunks)
        assert json_msgs[0]["text"] == "fallback content"

    def test_build_uses_doc_id_as_fallback_name(self, ragflow_tool: RAGFlowSearchTool):
        chunks = [
            {
                "content_with_weight": "content",
                "docnm_kwd": "",
                "doc_id": "fallback_doc_id",
                "important_kwd": [],
                "similarity": 0.5,
            }
        ]
        json_msgs, _model_msgs = ragflow_tool._build_result_messages(chunks)
        assert json_msgs[0]["filename"] == "fallback_doc_id"

    def test_build_empty_chunks(self, ragflow_tool: RAGFlowSearchTool):
        json_msgs, model_msgs = ragflow_tool._build_result_messages([])
        assert json_msgs == []
        assert model_msgs == []

    def test_build_truncates_important_words(self, ragflow_tool: RAGFlowSearchTool):
        chunks = [
            {
                "content_with_weight": "content",
                "docnm_kwd": "doc.txt",
                "important_kwd": ["a", "b", "c", "d", "e"],
                "similarity": 0.5,
            }
        ]
        json_msgs, _ = ragflow_tool._build_result_messages(chunks)
        assert json_msgs[0]["title"] == "doc.txt [a, b, c]"


# ---------------------------------------------------------------------------
# _search_ragflow
# ---------------------------------------------------------------------------

class TestSearchRAGFlow:
    def test_search_success(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_search_response()
        ragflow_tool._mock_http_client.post.return_value = mock_response

        result = ragflow_tool._search_ragflow("test query", ["dataset1", "dataset2"])

        assert len(result["chunks"]) == 2
        assert result["total"] == 2
        assert result["chunks"][0]["content_with_weight"] == "test content 1"

        ragflow_tool._mock_http_client.post.assert_called_once_with(
            "http://localhost:9380/api/v1/datasets/search",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test_api_key",
            },
            json={
                "question": "test query",
                "top_k": 3,
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "use_kg": False,
                "keyword": False,
                "highlight": True,
                "dataset_ids": ["dataset1", "dataset2"],
            },
        )

    def test_search_with_doc_ids(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_search_response()
        ragflow_tool._mock_http_client.post.return_value = mock_response

        result = ragflow_tool._search_ragflow("test query", ["dataset1"], doc_ids=["doc1", "doc2"])

        assert len(result["chunks"]) == 2
        call_json = ragflow_tool._mock_http_client.post.call_args[1]["json"]
        assert call_json["doc_ids"] == ["doc1", "doc2"]

    def test_search_single_dataset(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_search_response()
        ragflow_tool._mock_http_client.post.return_value = mock_response

        result = ragflow_tool._search_ragflow("query", ["dataset1"])
        assert len(result["chunks"]) == 2

    def test_search_api_error_code(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 102,
            "message": "Authentication failed",
            "data": {},
        }
        ragflow_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(RuntimeError, match="RAGFlow API returned error code 102"):
            ragflow_tool._search_ragflow("query", ["dataset1"])

    def test_search_request_error(self, ragflow_tool: RAGFlowSearchTool):
        ragflow_tool._mock_http_client.post.side_effect = httpx.RequestError(
            "Connection error", request=MagicMock()
        )

        with pytest.raises(ConnectionError, match="RAGFlow API request failed"):
            ragflow_tool._search_ragflow("query", ["dataset1"])

    def test_search_http_status_error(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=mock_response
        )
        ragflow_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(RuntimeError, match="RAGFlow API HTTP error"):
            ragflow_tool._search_ragflow("query", ["dataset1"])

    def test_search_json_decode_error(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        ragflow_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(ValueError, match="Failed to parse RAGFlow API response"):
            ragflow_tool._search_ragflow("query", ["dataset1"])


# ---------------------------------------------------------------------------
# forward
# ---------------------------------------------------------------------------

class TestForward:
    def _setup_success_flow(self, tool: RAGFlowSearchTool, chunks: List[dict] = None):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_search_response(chunks=chunks)
        tool._mock_http_client.post.return_value = mock_response

    def test_forward_success_with_observer_en(self, ragflow_tool: RAGFlowSearchTool):
        self._setup_success_flow(ragflow_tool)

        result_json = ragflow_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 2
        assert results[0]["title"] == "document1.txt [keyword1, keyword2]"
        assert results[0]["text"] == "test content 1"
        assert results[0]["index"] == "k1"

        # Check observer messages
        ragflow_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, ragflow_tool.running_prompt_en
        )
        ragflow_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD,
            json.dumps([{"icon": "search", "text": "test query"}], ensure_ascii=False),
        )
        ragflow_tool.observer.add_message.assert_any_call(
            "", ProcessType.SEARCH_CONTENT, ANY
        )

        assert ragflow_tool.record_ops == 3  # 1 + 2 results

    def test_forward_success_with_observer_zh(self, ragflow_tool: RAGFlowSearchTool):
        ragflow_tool.observer.lang = "zh"
        self._setup_success_flow(ragflow_tool)

        ragflow_tool.forward("测试查询")

        ragflow_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, ragflow_tool.running_prompt_zh
        )

    def test_forward_no_observer(self, ragflow_tool: RAGFlowSearchTool):
        ragflow_tool.observer = None
        self._setup_success_flow(ragflow_tool)

        result_json = ragflow_tool.forward("query")
        results = json.loads(result_json)
        assert len(results) == 2

    def test_forward_no_results(self, ragflow_tool: RAGFlowSearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_search_response(chunks=[], total=0)
        ragflow_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(ValueError, match="No results found!"):
            ragflow_tool.forward("test query")

    def test_forward_search_api_error(self, ragflow_tool: RAGFlowSearchTool):
        ragflow_tool._mock_http_client.post.side_effect = httpx.RequestError(
            "API error", request=MagicMock()
        )

        with pytest.raises(RuntimeError, match="Error searching RAGFlow knowledge base"):
            ragflow_tool.forward("test query")

    def test_forward_sorts_by_similarity_descending(self, ragflow_tool: RAGFlowSearchTool):
        chunks = [
            {"content_with_weight": "low", "docnm_kwd": "low.txt", "important_kwd": [],
             "similarity": 0.3, "term_similarity": 0.2, "vector_similarity": 0.35},
            {"content_with_weight": "high", "docnm_kwd": "high.txt", "important_kwd": [],
             "similarity": 0.95, "term_similarity": 0.9, "vector_similarity": 0.97},
            {"content_with_weight": "mid", "docnm_kwd": "mid.txt", "important_kwd": [],
             "similarity": 0.6, "term_similarity": 0.55, "vector_similarity": 0.62},
        ]
        self._setup_success_flow(ragflow_tool, chunks=chunks)

        result_json = ragflow_tool.forward("test query")
        results = json.loads(result_json)

        assert results[0]["text"] == "high"
        assert results[1]["text"] == "mid"
        assert results[2]["text"] == "low"

    def test_forward_respects_top_k(self, ragflow_tool: RAGFlowSearchTool):
        chunks = [
            {"content_with_weight": f"content{i}", "docnm_kwd": f"doc{i}.txt",
             "important_kwd": [], "similarity": 1.0 - i * 0.1}
            for i in range(10)
        ]
        self._setup_success_flow(ragflow_tool, chunks=chunks)

        result_json = ragflow_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == ragflow_tool.top_k

    def test_forward_with_doc_id_override(self, ragflow_tool: RAGFlowSearchTool):
        self._setup_success_flow(ragflow_tool)

        ragflow_tool.forward("test query", doc_id='["doc_a", "doc_b"]')

        call_json = ragflow_tool._mock_http_client.post.call_args[1]["json"]
        assert call_json["doc_ids"] == ["doc_a", "doc_b"]

    def test_forward_with_dataset_override(self, ragflow_tool: RAGFlowSearchTool):
        self._setup_success_flow(ragflow_tool)

        ragflow_tool.forward("test query", dataset_ids='["ds_override"]')

        call_json = ragflow_tool._mock_http_client.post.call_args[1]["json"]
        assert call_json["dataset_ids"] == ["ds_override"]
