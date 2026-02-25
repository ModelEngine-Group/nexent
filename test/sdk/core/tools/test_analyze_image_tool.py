import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sdk.nexent.core.tools import analyze_image_tool
from sdk.nexent.core.tools.analyze_image_tool import AnalyzeImageTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.fixture
def mock_storage_client():
    class DummyStorage:
        pass

    return DummyStorage()


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
        analyze_image_tool,
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
    return AnalyzeImageTool(
        observer=observer_en,
        vlm_model=mock_vlm_model,
        storage_client=mock_storage_client,
    )


class TestAnalyzeImageTool:
    def test_forward_impl_success_with_multiple_images(
        self, tool, mock_vlm_model, mock_prompt_loader
    ):
        mock_vlm_model.analyze_image.side_effect = [
            SimpleNamespace(content="First image analysis"),
            SimpleNamespace(content="Second image analysis"),
        ]

        result = tool._forward_impl([b"img1", b"img2"], "What is shown?")

        assert result == ["First image analysis", "Second image analysis"]
        assert mock_vlm_model.analyze_image.call_count == 2
        for call in mock_vlm_model.analyze_image.call_args_list:
            assert hasattr(call.kwargs["image_input"], "read")
        assert mock_prompt_loader == [("analyze_image", "en")]

    def test_forward_impl_zh_observer_messages(
        self, observer_zh, mock_vlm_model, mock_storage_client, mock_prompt_loader
    ):
        tool = AnalyzeImageTool(
            observer=observer_zh,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        mock_vlm_model.analyze_image.return_value = SimpleNamespace(
            content="描述")

        result = tool._forward_impl([b"img"], "问题")

        assert result == ["描述"]
        assert mock_prompt_loader == [("analyze_image", "zh")]

    @pytest.mark.parametrize(
        "image_list,error_message",
        [
            (None, "image_urls cannot be None"),
            ("not-a-list", "image_urls must be a list of bytes"),
            ([], "image_urls must contain at least one image"),
        ],
    )
    def test_forward_impl_validates_inputs(
        self, tool, image_list, error_message
    ):
        with pytest.raises(ValueError, match=error_message):
            tool._forward_impl(image_list, "question")

    def test_forward_impl_wraps_model_errors(
        self, tool, mock_vlm_model, mock_prompt_loader
    ):
        mock_vlm_model.analyze_image.side_effect = Exception("model failed")

        with pytest.raises(
            Exception,
            match="Error analyzing image: Failed to analyze image 1: model failed",
        ):
            tool._forward_impl([b"img"], "question")

        mock_vlm_model.analyze_image.assert_called_once()


class TestAnalyzeImageToolEdgeCases:
    """Test edge cases and additional scenarios for AnalyzeImageTool."""

    def test_forward_impl_vlm_model_none(self, observer_en, mock_storage_client):
        """Test that exception is raised when VLM model is None."""
        tool = AnalyzeImageTool(
            observer=observer_en,
            vlm_model=None,
            storage_client=mock_storage_client,
        )

        with pytest.raises(Exception) as exc_info:
            tool._forward_impl([b"img"], "question")

        assert "Vision Language Model (VLM) is not configured" in str(
            exc_info.value)

    def test_forward_impl_vlm_model_none_chinese(self, observer_zh, mock_storage_client):
        """Test that exception is raised in Chinese when VLM model is None and observer is Chinese."""
        tool = AnalyzeImageTool(
            observer=observer_zh,
            vlm_model=None,
            storage_client=mock_storage_client,
        )

        with pytest.raises(Exception) as exc_info:
            tool._forward_impl([b"img"], "问题")

        assert "视觉语言模型(VLM)未配置" in str(exc_info.value)

    def test_forward_impl_observer_none_uses_english(self, mock_vlm_model, mock_storage_client):
        """Test that English is used when observer is None."""
        tool = AnalyzeImageTool(
            observer=None,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        mock_vlm_model.analyze_image.return_value = SimpleNamespace(
            content="Analysis result")

        result = tool._forward_impl([b"img"], "question")

        assert result == ["Analysis result"]

    def test_forward_impl_single_image_success(self, tool, mock_vlm_model, mock_prompt_loader):
        """Test successful analysis with a single image."""
        mock_vlm_model.analyze_image.return_value = SimpleNamespace(
            content="Single image description")

        result = tool._forward_impl(
            [b"single_image"], "What is in this image?")

        assert result == ["Single image description"]
        mock_vlm_model.analyze_image.assert_called_once()

    def test_is_chinese_property_english(self, observer_en, mock_vlm_model, mock_storage_client):
        """Test that _is_chinese is False when observer lang is English."""
        tool = AnalyzeImageTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool._is_chinese is False

    def test_is_chinese_property_chinese(self, observer_zh, mock_vlm_model, mock_storage_client):
        """Test that _is_chinese is True when observer lang is Chinese."""
        tool = AnalyzeImageTool(
            observer=observer_zh,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool._is_chinese is True

    def test_is_chinese_property_no_observer(self, mock_vlm_model, mock_storage_client):
        """Test that _is_chinese is False when observer is None."""
        tool = AnalyzeImageTool(
            observer=None,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool._is_chinese is False

    def test_running_prompt_properties(self, observer_en, observer_zh, mock_vlm_model, mock_storage_client):
        """Test that running prompt properties are set correctly."""
        tool_en = AnalyzeImageTool(
            observer=observer_en,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        tool_zh = AnalyzeImageTool(
            observer=observer_zh,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        assert tool_en.running_prompt_en == "Analyzing image..."
        assert tool_en.running_prompt_zh == "正在分析图片..."
        assert tool_zh.running_prompt_en == "Analyzing image..."
        assert tool_zh.running_prompt_zh == "正在分析图片..."

    def test_load_save_object_manager_created(self, mock_vlm_model, mock_storage_client):
        """Test that LoadSaveObjectManager is created with storage client."""
        with patch('sdk.nexent.core.tools.analyze_image_tool.LoadSaveObjectManager') as mock_manager_class:
            mock_manager_instance = MagicMock()
            mock_manager_class.return_value = mock_manager_instance
            mock_manager_instance.load_object.return_value = lambda x: x

            tool = AnalyzeImageTool(
                observer=MagicMock(),
                vlm_model=mock_vlm_model,
                storage_client=mock_storage_client,
            )

            mock_manager_class.assert_called_once_with(
                storage_client=mock_storage_client)

    def test_observer_add_message_called(self, tool, mock_vlm_model, mock_prompt_loader):
        """Test that observer.add_message is called with running prompt."""
        mock_vlm_model.analyze_image.return_value = SimpleNamespace(
            content="Result")

        tool._forward_impl([b"img"], "question")

        tool.observer.add_message.assert_called_once()
        call_args = tool.observer.add_message.call_args
        assert call_args[0][0] == ""  # first arg is empty string
        assert call_args[0][1] == ProcessType.TOOL
        assert call_args[0][2] == "Analyzing image..."

    def test_observer_add_message_not_called_when_none(self, mock_vlm_model, mock_storage_client):
        """Test that observer.add_message is not called when observer is None."""
        tool = AnalyzeImageTool(
            observer=None,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )
        mock_vlm_model.analyze_image.return_value = SimpleNamespace(
            content="Result")

        # Should not raise any exception
        result = tool._forward_impl([b"img"], "question")

        assert result == ["Result"]
        mock_vlm_model.analyze_image.assert_called_once()

    def test_tool_name_and_description(self, tool):
        """Test that tool name and description are set correctly."""
        assert tool.name == "analyze_image"
        assert "visual language model" in tool.description.lower()
        assert "image" in tool.description.lower()

    def test_tool_inputs_schema(self, tool):
        """Test that tool inputs schema is correctly defined."""
        assert "image_urls_list" in tool.inputs
        assert "query" in tool.inputs
        assert tool.inputs["image_urls_list"]["type"] == "array"
        assert tool.inputs["query"]["type"] == "string"
        assert tool.output_type == "array"

    def test_tool_category_and_sign(self, tool):
        """Test that tool category and sign are set correctly."""
        from sdk.nexent.core.utils.tools_common_message import ToolCategory, ToolSign
        assert tool.category == ToolCategory.MULTIMODAL.value
        assert tool.tool_sign == ToolSign.MULTIMODAL_OPERATION.value

    @pytest.mark.parametrize("lang,expected_prompt", [
        ("en", "Analyzing image..."),
        ("zh", "正在分析图片..."),
    ])
    def test_running_prompt_by_language(self, mock_vlm_model, mock_storage_client, lang, expected_prompt):
        """Test that running prompt is correctly selected based on language."""
        observer = MagicMock(spec=MessageObserver)
        observer.lang = lang

        tool = AnalyzeImageTool(
            observer=observer,
            vlm_model=mock_vlm_model,
            storage_client=mock_storage_client,
        )

        mock_vlm_model.analyze_image.return_value = SimpleNamespace(
            content="result")
        tool._forward_impl([b"img"], "question")

        # Get the actual prompt passed to add_message
        call_args = tool.observer.add_message.call_args[0]
        assert call_args[2] == expected_prompt
