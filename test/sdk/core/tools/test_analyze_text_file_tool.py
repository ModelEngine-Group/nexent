from unittest.mock import MagicMock, patch

import pytest

import sdk.nexent.core.tools.analyze_text_file_tool as module
from sdk.nexent.core.tools.analyze_text_file_tool import AnalyzeTextFileTool, ProcessType


class _NoopLoadSaveObjectManager:
    """Simplified LoadSaveObjectManager replacement for tests."""

    def __init__(self, *_, **__):
        pass

    def load_object(self, *_, **__):
        def decorator(func):
            return func

        return decorator


@pytest.fixture(autouse=True)
def patch_load_save_manager(monkeypatch):
    monkeypatch.setattr(module, "LoadSaveObjectManager",
                        _NoopLoadSaveObjectManager)


@pytest.fixture
def llm_model():
    return MagicMock()


@pytest.fixture
def observer_zh():
    obs = MagicMock()
    obs.lang = "zh"
    return obs


@pytest.fixture
def observer_en():
    obs = MagicMock()
    obs.lang = "en"
    return obs


@pytest.fixture
def http_client_manager(mocker):
    """Fixture to mock http_client_manager for tests."""
    mock = mocker.patch(
        "sdk.nexent.core.tools.analyze_text_file_tool.http_client_manager"
    )
    mock_client = MagicMock()
    mock.get_sync_client.return_value = mock_client
    return mock, mock_client


@pytest.fixture
def tool(http_client_manager, observer_zh, llm_model):
    """Fixture to create AnalyzeTextFileTool instance with mocked HTTP client."""
    mock_manager, mock_client = http_client_manager
    tool_instance = AnalyzeTextFileTool(
        storage_client=MagicMock(),
        observer=observer_zh,
        data_process_service_url="http://data-process",
        llm_model=llm_model,
    )
    # Store the mock client for tests to use
    tool_instance._mock_http_client = mock_client
    return tool_instance


class TestAnalyzeTextFileTool:
    def test_forward_impl_switches_language(self, observer_en, llm_model, monkeypatch):
        tool = AnalyzeTextFileTool(
            storage_client=MagicMock(),
            observer=observer_en,
            data_process_service_url="http://data-process",
            llm_model=llm_model,
        )
        tool.process_text_file = MagicMock(return_value="text")
        tool.analyze_file = MagicMock(return_value=("answer", 0.0))

        result = tool._forward_impl([b"x"], "question")

        assert result == ["answer"]
        observer_en.add_message.assert_any_call("", ProcessType.TOOL, "Analyzing file...")

    @pytest.mark.parametrize(
        "payload,error",
        [
            (None, "file_url_list cannot be None"),
            ("not-a-list", "file_url_list must be a list of bytes"),
        ],
    )
    def test_forward_impl_validates_inputs(self, tool, payload, error):
        with pytest.raises(ValueError, match=error):
            tool._forward_impl(payload, "prompt")

    def test_forward_impl_raises_when_no_text(self, tool):
        tool.process_text_file = MagicMock(return_value="")

        with pytest.raises(Exception, match="No text content extracted"):
            tool._forward_impl([b"file"], "prompt")

    def test_forward_impl_appends_analysis_exception(self, tool):
        tool.process_text_file = MagicMock(return_value="text")
        tool.analyze_file = MagicMock(side_effect=Exception("LLM failed"))

        result = tool._forward_impl([b"x"], "prompt")

        assert result == ["LLM failed"]

    def test_process_text_file_success(self, tool):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"text": "converted"}
        tool._mock_http_client.post.return_value = mock_response

        result = tool.process_text_file("doc.txt", b"bytes")

        assert result == "converted"
        tool._mock_http_client.post.assert_called_once()

    def test_process_text_file_http_error_json_detail(self, tool):
        mock_response = MagicMock(status_code=400)
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"detail": "bad request"}
        tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception, match="bad request"):
            tool.process_text_file("doc.txt", b"bytes")

    def test_process_text_file_http_error_plain_text(self, tool):
        mock_response = MagicMock(status_code=500)
        mock_response.headers = {}
        mock_response.text = "server exploded"
        tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception, match="server exploded"):
            tool.process_text_file("doc.txt", b"bytes")

    def test_analyze_file_uses_prompt_template(self, tool, llm_model, observer_zh, monkeypatch):
        prompts = {
            "system_prompt": "System prompt for {{query}}",
            "user_prompt": "User prompt"
        }
        monkeypatch.setattr(module, "get_prompt_template",
                            lambda template_type, language: prompts)
        llm_model.analyze_long_text.return_value = (
            MagicMock(content="analysis"), 12.5)

        result = tool.analyze_file("Summarize", "Long text")

        assert result == ("analysis", 12.5)
        llm_model.analyze_long_text.assert_called_once()
        kwargs = llm_model.analyze_long_text.call_args.kwargs
        assert kwargs["system_prompt"] == "System prompt for Summarize"

    def test_analyze_file_defaults_to_english(self, tool, llm_model, monkeypatch):
        tool.observer = None
        mock_get_template = MagicMock(return_value={
            "system_prompt": "{{query}}",
            "user_prompt": "",
        })
        monkeypatch.setattr(module, "get_prompt_template", mock_get_template)
        llm_model.analyze_long_text.return_value = (
            MagicMock(content="analysis"), 0)

        result = tool.analyze_file("Explain", "text")

        assert result == ("analysis", 0)
        mock_get_template.assert_called_once_with(
            template_type="analyze_file", language="en")
