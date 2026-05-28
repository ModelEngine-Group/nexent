from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sdk.nexent.core.tools import analyze_audio_tool, analyze_video_tool
from sdk.nexent.core.tools.analyze_audio_tool import AnalyzeAudioTool
from sdk.nexent.core.tools.analyze_video_tool import AnalyzeVideoTool
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
def observer_en():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


def test_analyze_audio_uses_video_understanding_model(observer_en, mock_vlm_model, mock_storage_client, monkeypatch):
    calls = []

    def _fake_get_prompt(template_type, language=None, **_):
        calls.append((template_type, language))
        return {"system_prompt": "Analyze audio for {{ query }}"}

    monkeypatch.setattr(analyze_audio_tool, "get_prompt_template", _fake_get_prompt)
    mock_vlm_model.analyze_audio.return_value = SimpleNamespace(content="audio result")
    tool = AnalyzeAudioTool(
        observer=observer_en,
        vlm_model=mock_vlm_model,
        storage_client=mock_storage_client,
    )

    result = tool._forward_impl(audio_url=b"ID3audio-bytes", query="what happened?")

    assert result == "audio result"
    assert calls == [("analyze_audio", "en")]
    mock_vlm_model.analyze_audio.assert_called_once()
    call_kwargs = mock_vlm_model.analyze_audio.call_args.kwargs
    assert hasattr(call_kwargs["audio_input"], "read")
    assert call_kwargs["content_type"].startswith("audio/")
    observer_en.add_message.assert_called_once_with("", ProcessType.TOOL, "Analyzing audio...")


def test_analyze_audio_schema_uses_single_url():
    assert "audio_url" in AnalyzeAudioTool.inputs
    assert "audio_urls_list" not in AnalyzeAudioTool.inputs
    assert AnalyzeAudioTool.output_type == "string"


def test_analyze_audio_accepts_legacy_url_list(observer_en, mock_vlm_model, mock_storage_client, monkeypatch):
    monkeypatch.setattr(
        analyze_audio_tool,
        "get_prompt_template",
        lambda template_type, language=None, **_: {"system_prompt": "Analyze audio for {{ query }}"},
    )
    mock_vlm_model.analyze_audio.return_value = SimpleNamespace(content="audio result")
    tool = AnalyzeAudioTool(
        observer=observer_en,
        vlm_model=mock_vlm_model,
        storage_client=mock_storage_client,
    )

    result = tool._forward_impl(audio_urls_list=[b"ID3audio-bytes"], query="what happened?")

    assert result == "audio result"


def test_analyze_audio_rejects_siliconflow_non_omni_model(observer_en, mock_storage_client):
    vlm_model = SimpleNamespace(
        model_id="Qwen/Qwen3-VL-32B-Instruct",
        client_kwargs={"base_url": "https://api.siliconflow.cn/v1"},
    )
    tool = AnalyzeAudioTool(
        observer=observer_en,
        vlm_model=vlm_model,
        storage_client=mock_storage_client,
    )

    with pytest.raises(ValueError) as exc_info:
        tool._forward_impl(audio_url=b"ID3audio-bytes", query="what happened?")

    assert "Please choose a Qwen3-Omni model" in str(exc_info.value)


def test_analyze_video_uses_video_understanding_model(observer_en, mock_vlm_model, mock_storage_client, monkeypatch):
    calls = []

    def _fake_get_prompt(template_type, language=None, **_):
        calls.append((template_type, language))
        return {"system_prompt": "Analyze video for {{ query }}"}

    monkeypatch.setattr(analyze_video_tool, "get_prompt_template", _fake_get_prompt)
    mock_vlm_model.analyze_video.return_value = SimpleNamespace(content="video result")
    tool = AnalyzeVideoTool(
        observer=observer_en,
        vlm_model=mock_vlm_model,
        storage_client=mock_storage_client,
    )

    result = tool._forward_impl(video_url=b"\x00\x00\x00\x18ftypmp42video-bytes", query="what happened?")

    assert result == "video result"
    assert calls == [("analyze_video", "en")]
    mock_vlm_model.analyze_video.assert_called_once()
    call_kwargs = mock_vlm_model.analyze_video.call_args.kwargs
    assert hasattr(call_kwargs["video_input"], "read")
    assert call_kwargs["content_type"].startswith("video/")
    observer_en.add_message.assert_called_once_with("", ProcessType.TOOL, "Analyzing video...")


def test_analyze_video_schema_uses_single_url():
    assert "video_url" in AnalyzeVideoTool.inputs
    assert "video_urls_list" not in AnalyzeVideoTool.inputs
    assert AnalyzeVideoTool.output_type == "string"


def test_analyze_video_accepts_legacy_url_list(observer_en, mock_vlm_model, mock_storage_client, monkeypatch):
    monkeypatch.setattr(
        analyze_video_tool,
        "get_prompt_template",
        lambda template_type, language=None, **_: {"system_prompt": "Analyze video for {{ query }}"},
    )
    mock_vlm_model.analyze_video.return_value = SimpleNamespace(content="video result")
    tool = AnalyzeVideoTool(
        observer=observer_en,
        vlm_model=mock_vlm_model,
        storage_client=mock_storage_client,
    )

    result = tool._forward_impl(video_urls_list=[b"\x00\x00\x00\x18ftypmp42video-bytes"], query="what happened?")

    assert result == "video result"


@pytest.mark.parametrize(
    "tool_class,input_name,error_text",
    [
        (AnalyzeAudioTool, "audio_urls_list", "Video understanding model is not configured"),
        (AnalyzeVideoTool, "video_urls_list", "Video understanding model is not configured"),
    ],
)
def test_analyze_audio_video_require_video_understanding_model(
        tool_class, input_name, error_text, observer_en, mock_storage_client):
    tool = tool_class(
        observer=observer_en,
        vlm_model=None,
        storage_client=mock_storage_client,
    )

    with pytest.raises(Exception) as exc_info:
        tool._forward_impl(**{input_name: [b"media"], "query": "question"})

    assert error_text in str(exc_info.value)
