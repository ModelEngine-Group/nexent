# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from unittest.mock import MagicMock, patch

import pytest

import sdk.nexent.core.tools.analyze_text_file_tool as module
from sdk.nexent.core.tools.analyze_text_file_tool import AnalyzeTextFileTool


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
def tool(observer_zh, llm_model):
    return AnalyzeTextFileTool(storage_client=MagicMock(), observer=observer_zh,
                               text_cleanser=MagicMock(return_value="text"), llm_model=llm_model)


class TestAnalyzeTextFileTool:
    def test_forward_impl_switches_language(self, observer_en, llm_model, monkeypatch):
        tool = AnalyzeTextFileTool(
            storage_client=MagicMock(),
            observer=observer_en,
            text_cleanser=MagicMock(return_value="text"),
            llm_model=llm_model,
        )
        tool.text_cleanser = MagicMock(return_value="text")
        tool.analyze_file = MagicMock(return_value=("answer", 0.0))

        result = tool._forward_impl([b"x"], "question")

        assert result == ["answer"]
        tool.text_cleanser.assert_called_once_with("file_1.txt", b"x", cancellation_scope=None)
    @pytest.mark.parametrize(
        "payload",
        [
            b'{"name":"alice","age":18}',
            b'[{"id":1},{"id":2}]',
        ],
    )
    def test_forward_impl_preserves_json_format(self, tool, payload):
        tool.text_cleanser = MagicMock(return_value="text")
        tool.analyze_file = MagicMock(return_value=("answer", 0.0))

        result = tool._forward_impl([payload], "question")

        assert result == ["answer"]
        tool.text_cleanser.assert_called_once_with("file_1.json", payload, cancellation_scope=None)

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
        tool.text_cleanser = MagicMock(return_value="")

        with pytest.raises(Exception, match="No text content extracted"):
            tool._forward_impl([b"file"], "prompt")

    def test_forward_impl_appends_analysis_exception(self, tool):
        tool.text_cleanser = MagicMock(return_value="text")
        tool.analyze_file = MagicMock(side_effect=Exception("LLM failed"))

        result = tool._forward_impl([b"x"], "prompt")

        assert result == ["LLM failed"]

    def test_cleansing_error_is_not_retried_or_sent_to_model(self, tool):
        tool.text_cleanser.side_effect = OSError("cleanse-failed")
        tool.analyze_file = MagicMock()
        with pytest.raises(Exception, match="cleanse-failed"):
            tool._forward_impl([b"input"], "query")
        assert tool.text_cleanser.call_count == 1
        tool.analyze_file.assert_not_called()

    @pytest.mark.parametrize("capability", [None, "old-service-url"])
    def test_missing_capability_rejected_without_legacy_entry(self, capability):
        with pytest.raises(ValueError, match="capability is required"):
            AnalyzeTextFileTool(text_cleanser=capability)
        assert not hasattr(AnalyzeTextFileTool, "process_text_file")

    def test_analyze_file_uses_prompt_template(self, tool, llm_model, observer_zh, monkeypatch):
        prompts = {
            "system_prompt": "System prompt for {{query}}",
            "user_prompt": "User prompt"
        }
        monkeypatch.setattr(module, "load_prompt",
                            lambda language, path: prompts)
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
        monkeypatch.setattr(module, "load_prompt", mock_get_template)
        llm_model.analyze_long_text.return_value = (
            MagicMock(content="analysis"), 0)

        result = tool.analyze_file("Explain", "text")

        assert result == ("analysis", 0)
        mock_get_template.assert_called_once_with("en", "tool/analyze_file")


class TestAnalyzeTextFileToolValidateUrlAccess:
    """Test cases for validate_url_access parameter in AnalyzeTextFileTool."""

    def test_load_save_object_manager_created_with_validate_url_access_none(
        self, observer_en, llm_model
    ):
        """Test that LoadSaveObjectManager is called with validate_url_access=None by default."""
        with patch.object(module, 'LoadSaveObjectManager') as mock_manager_class:
            mock_manager_instance = MagicMock()
            mock_manager_class.return_value = mock_manager_instance
            mock_manager_instance.load_object.return_value = lambda x: x

            tool = AnalyzeTextFileTool(
                storage_client=MagicMock(),
                observer=observer_en,
                text_cleanser=MagicMock(return_value="text"),
                llm_model=llm_model,
            )

            mock_manager_class.assert_called_once_with(
                storage_client=tool.storage_client,
                validate_url_access=None
            )

    def test_load_save_object_manager_with_validate_url_access_callable(
        self, observer_en, llm_model
    ):
        """Test that callable validate_url_access is passed to LoadSaveObjectManager."""
        with patch.object(module, 'LoadSaveObjectManager') as mock_manager_class:
            mock_manager_instance = MagicMock()
            mock_manager_class.return_value = mock_manager_instance
            mock_manager_instance.load_object.return_value = lambda x: x

            validate_callback = MagicMock()

            tool = AnalyzeTextFileTool(
                storage_client=MagicMock(),
                observer=observer_en,
                text_cleanser=MagicMock(return_value="text"),
                llm_model=llm_model,
                validate_url_access=validate_callback,
            )

            mock_manager_class.assert_called_once_with(
                storage_client=tool.storage_client,
                validate_url_access=validate_callback
            )

    def test_load_save_object_manager_validate_url_access_not_callable(
        self, observer_en, llm_model
    ):
        """Test that non-callable validate_url_access is converted to None."""
        with patch.object(module, 'LoadSaveObjectManager') as mock_manager_class:
            mock_manager_instance = MagicMock()
            mock_manager_class.return_value = mock_manager_instance
            mock_manager_instance.load_object.return_value = lambda x: x

            tool = AnalyzeTextFileTool(
                storage_client=MagicMock(),
                observer=observer_en,
                text_cleanser=MagicMock(return_value="text"),
                llm_model=llm_model,
                validate_url_access="not_a_callable",
            )

            mock_manager_class.assert_called_once_with(
                storage_client=tool.storage_client,
                validate_url_access=None
            )

    def test_load_save_object_manager_validate_url_access_lambda(
        self, observer_en, llm_model
    ):
        """Test that lambda validate_url_access is passed to LoadSaveObjectManager."""
        with patch.object(module, 'LoadSaveObjectManager') as mock_manager_class:
            mock_manager_instance = MagicMock()
            mock_manager_class.return_value = mock_manager_instance
            mock_manager_instance.load_object.return_value = lambda x: x

            validate_callback = lambda url: True

            tool = AnalyzeTextFileTool(
                storage_client=MagicMock(),
                observer=observer_en,
                text_cleanser=MagicMock(return_value="text"),
                llm_model=llm_model,
                validate_url_access=validate_callback,
            )

            mock_manager_class.assert_called_once_with(
                storage_client=tool.storage_client,
                validate_url_access=validate_callback
            )

    def test_init_param_descriptions_has_validate_url_access(
        self, observer_en, llm_model
    ):
        """Test that init_param_descriptions includes validate_url_access."""
        tool = AnalyzeTextFileTool(
            storage_client=MagicMock(),
            observer=observer_en,
            text_cleanser=MagicMock(return_value="text"),
            llm_model=llm_model,
        )

        assert "validate_url_access" in tool.init_param_descriptions
        assert "Callback function to validate URL access permissions (passed to LoadSaveObjectManager)" in tool.init_param_descriptions["validate_url_access"]["description"]
