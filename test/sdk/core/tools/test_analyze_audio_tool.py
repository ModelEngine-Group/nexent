from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.core.tools import analyze_audio_tool
from sdk.nexent.core.tools import AnalyzeAudioTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType


class _NoopLoadSaveObjectManager:
    """Simplified LoadSaveObjectManager replacement for tests."""

    def __init__(self, *_, **__):
        pass

    def load_object(self, *_, **__):
        def decorator(func):
            return func

        return decorator

    def download_file_from_url(self, url, url_type):
        return b"mock_audio_data"


@pytest.fixture(autouse=True)
def patch_load_save_manager(monkeypatch):
    monkeypatch.setattr(
        analyze_audio_tool,
        "LoadSaveObjectManager",
        _NoopLoadSaveObjectManager
    )


@pytest.fixture
def mock_storage_client():
    return MagicMock()


@pytest.fixture
def mock_vlm_model():
    return MagicMock()


@pytest.fixture
def mock_prompt_loader(monkeypatch):
    calls = []

    def _fake_get_prompt(template_type, language=None, **_):
        calls.append((template_type, language))
        return {"system_prompt": "Describe {{ query }}"}

    monkeypatch.setattr(
        analyze_audio_tool,
        "get_prompt_template",
        _fake_get_prompt,
    )
    return calls


@pytest.fixture
def observer_en():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def observer_zh():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "zh"
    return observer


@pytest.fixture
def tool(observer_en, mock_vlm_model, mock_storage_client):
    return AnalyzeAudioTool(
        observer=observer_en,
        vlm_model=mock_vlm_model,
        storage_client=mock_storage_client,
    )


class TestAnalyzeAudioTool:
    def test_forward_impl_success_with_single_audio(
        self, tool, mock_vlm_model, mock_prompt_loader
    ):
        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="This is a speech about machine learning"
        )

        result = tool._forward_impl([b"audio_data"], "What is this audio about?")

        assert result == ["This is a speech about machine learning"]
        assert mock_vlm_model.analyze_audio.call_count == 1
        assert mock_prompt_loader == [("analyze_audio", "en")]

    def test_forward_impl_success_with_multiple_audios(
        self, tool, mock_vlm_model, mock_prompt_loader
    ):
        mock_vlm_model.analyze_audio.side_effect = [
            SimpleNamespace(content="First audio analysis"),
            SimpleNamespace(content="Second audio analysis"),
        ]

        result = tool._forward_impl([b"audio1", b"audio2"], "Transcribe this")

        assert result == ["First audio analysis", "Second audio analysis"]
        assert mock_vlm_model.analyze_audio.call_count == 2

    def test_forward_impl_zh_observer_messages(
        self, observer_zh, mock_vlm_model, mock_storage_client, mock_prompt_loader
    ):
        tool = AnalyzeAudioTool(
            observer=observer_zh,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="这是一段关于机器学习的演讲"
        )

        result = tool._forward_impl([b"audio"], "这段音频是关于什么的？")

        assert result == ["这是一段关于机器学习的演讲"]
        assert mock_prompt_loader == [("analyze_audio", "zh")]

    @pytest.mark.parametrize(
        "audio_list,error_message",
        [
            (None, "audio_urls cannot be None"),
            ("not-a-list", "audio_urls must be a list of bytes"),
            ([], "audio_urls must contain at least one audio file"),
        ],
    )
    def test_forward_impl_validates_inputs(
        self, tool, audio_list, error_message
    ):
        with pytest.raises(ValueError, match=error_message):
            tool._forward_impl(audio_list, "question")

    def test_forward_impl_wraps_model_errors(
        self, tool, mock_vlm_model, mock_prompt_loader
    ):
        mock_vlm_model.analyze_audio.side_effect = Exception("model failed")

        with pytest.raises(
            Exception,
            match="Error analyzing audio: Failed to analyze audio 1: model failed",
        ):
            tool._forward_impl([b"audio"], "question")

        mock_vlm_model.analyze_audio.assert_called_once()


class TestAnalyzeAudioToolEdgeCases:
    """Test edge cases and additional scenarios for AnalyzeAudioTool."""

    def test_forward_impl_vlm_model_none(self, observer_en, mock_storage_client):
        """Test that exception is raised when VLM model is None."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=None,
            storage_client=mock_storage_client,
        )

        with pytest.raises(Exception) as exc_info:
            tool._forward_impl([b"audio"], "question")

        assert "Language model is not configured" in str(exc_info.value)

    def test_forward_impl_vlm_model_none_chinese(self, observer_zh, mock_storage_client):
        """Test that exception is raised in Chinese when VLM model is None and observer is Chinese."""
        tool = AnalyzeAudioTool(
            observer=observer_zh,
            vlm_model=None,
            storage_client=mock_storage_client,
        )

        with pytest.raises(Exception) as exc_info:
            tool._forward_impl([b"audio"], "question")

        assert "语言模型未配置" in str(exc_info.value)

    def test_forward_impl_observer_none_uses_english(self, mock_vlm_model, mock_storage_client):
        """Test that English is used when observer is None."""
        tool = AnalyzeAudioTool(
            observer=None,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="Analysis result")

        result = tool._forward_impl([b"audio"], "question")

        assert result == ["Analysis result"]

    def test_forward_impl_single_audio_success(self, tool, mock_vlm_model, mock_prompt_loader):
        """Test successful analysis with a single audio."""
        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="Single audio description")

        result = tool._forward_impl([b"single_audio"], "What is in this audio?")

        assert result == ["Single audio description"]
        mock_vlm_model.analyze_audio.assert_called_once()

    def test_is_chinese_property_english(self, observer_en, mock_vlm_model, mock_storage_client):
        """Test that _is_chinese is False when observer lang is English."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool._is_chinese is False

    def test_is_chinese_property_chinese(self, observer_zh, mock_vlm_model, mock_storage_client):
        """Test that _is_chinese is True when observer lang is Chinese."""
        tool = AnalyzeAudioTool(
            observer=observer_zh,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool._is_chinese is True

    def test_is_chinese_property_no_observer(self, mock_vlm_model, mock_storage_client):
        """Test that _is_chinese is False when observer is None."""
        tool = AnalyzeAudioTool(
            observer=None,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool._is_chinese is False

    def test_running_prompt_properties(self, observer_en, observer_zh, mock_vlm_model, mock_storage_client):
        """Test that running prompt properties are set correctly."""
        tool_en = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        tool_zh = AnalyzeAudioTool(
            observer=observer_zh,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool_en.running_prompt_en == "Analyzing audio..."
        assert tool_en.running_prompt_zh == "正在分析音频..."
        assert tool_zh.running_prompt_en == "Analyzing audio..."
        assert tool_zh.running_prompt_zh == "正在分析音频..."

    def test_observer_add_message_called(self, tool, mock_vlm_model, mock_prompt_loader):
        """Test that observer.add_message is called with running prompt."""
        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="Result")

        tool._forward_impl([b"audio"], "question")

        tool.observer.add_message.assert_called_once()
        call_args = tool.observer.add_message.call_args
        assert call_args[0][0] == ""  # first arg is empty string
        assert call_args[0][1] == ProcessType.TOOL
        assert call_args[0][2] == "Analyzing audio..."

    def test_observer_add_message_not_called_when_none(self, mock_vlm_model, mock_storage_client):
        """Test that observer.add_message is not called when observer is None."""
        tool = AnalyzeAudioTool(
            observer=None,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="Result")

        result = tool._forward_impl([b"audio"], "question")

        assert result == ["Result"]
        mock_vlm_model.analyze_audio.assert_called_once()

    def test_tool_name_and_description(self, tool):
        """Test that tool name and description are set correctly."""
        assert tool.name == "analyze_audio"
        assert "language model" in tool.description.lower()
        assert "audio" in tool.description.lower()

    def test_tool_inputs_schema(self, tool):
        """Test that tool inputs schema is correctly defined."""
        assert "audio_url" in tool.inputs
        assert "audio_urls_list" in tool.inputs
        assert "query" in tool.inputs
        assert tool.inputs["audio_url"]["type"] == "string"
        assert tool.inputs["audio_urls_list"]["type"] == "array"
        assert tool.inputs["query"]["type"] == "string"
        assert tool.inputs["audio_url"]["nullable"] is True
        assert tool.inputs["audio_urls_list"]["nullable"] is True
        assert tool.inputs["query"]["nullable"] is True
        assert tool.output_type == "array"

    def test_tool_category_and_sign(self, tool):
        """Test that tool category and sign are set correctly."""
        from sdk.nexent.core.utils.tools_common_message import ToolCategory, ToolSign
        assert tool.category == ToolCategory.MULTIMODAL.value
        assert tool.tool_sign == ToolSign.MULTIMODAL_OPERATION.value

    @pytest.mark.parametrize("lang,expected_prompt", [
        ("en", "Analyzing audio..."),
        ("zh", "正在分析音频..."),
    ])
    def test_running_prompt_by_language(self, mock_vlm_model, mock_storage_client, lang, expected_prompt):
        """Test that running prompt is correctly selected based on language."""
        observer = MagicMock(spec=MessageObserver)
        observer.lang = lang

        tool = AnalyzeAudioTool(
            observer=observer,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(
            content="result")
        tool._forward_impl([b"audio"], "question")

        call_args = tool.observer.add_message.call_args[0]
        assert call_args[2] == expected_prompt


class TestAnalyzeAudioToolForward:
    """Test the forward method which handles URL downloads."""

    def test_forward_with_single_url(self, observer_en, mock_vlm_model, mock_storage_client, monkeypatch):
        """Test that forward method downloads and processes single URL."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        mock_download = MagicMock(return_value=b"downloaded_audio")
        monkeypatch.setattr(tool.mm, "download_file_from_url", mock_download)

        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(content="transcript")

        result = tool.forward(audio_url="s3://bucket/audio.mp3", query="Transcribe")

        assert result == ["transcript"]
        mock_download.assert_called_once()

    def test_forward_with_urls_list(self, observer_en, mock_vlm_model, mock_storage_client, monkeypatch):
        """Test that forward method downloads and processes list of URLs."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        mock_download = MagicMock(return_value=b"downloaded_audio")
        monkeypatch.setattr(tool.mm, "download_file_from_url", mock_download)

        mock_vlm_model.analyze_audio.return_value = SimpleNamespace(content="transcript")

        result = tool.forward(audio_urls_list=["s3://bucket/audio1.mp3", "s3://bucket/audio2.mp3"], query="Transcribe")

        assert result == ["transcript", "transcript"]
        assert mock_download.call_count == 2

    def test_forward_empty_urls_raises_error(self, observer_en, mock_vlm_model, mock_storage_client):
        """Test that forward method raises error when no URLs provided."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        with pytest.raises(ValueError, match="audio_urls_list cannot be empty"):
            tool.forward(query="Transcribe")

    def test_forward_invalid_url_raises_error(self, observer_en, mock_vlm_model, mock_storage_client):
        """Test that forward method raises error for invalid URL."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        mock_download = MagicMock(return_value=None)
        tool.mm.download_file_from_url = mock_download

        with pytest.raises(ValueError, match="Invalid URL"):
            tool.forward(audio_url="invalid_url", query="Transcribe")

    def test_forward_download_failed_raises_error(self, observer_en, mock_vlm_model, mock_storage_client):
        """Test that forward method raises error when download fails."""
        tool = AnalyzeAudioTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        mock_download = MagicMock(return_value=None)
        tool.mm.download_file_from_url = mock_download

        with pytest.raises(ValueError, match="Failed to download audio"):
            tool.forward(audio_url="s3://bucket/audio.mp3", query="Transcribe")
