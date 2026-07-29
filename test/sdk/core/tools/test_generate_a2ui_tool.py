import json
from types import SimpleNamespace

import pytest

from nexent.core.a2ui import A2UIValidationError
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.tools.generate_a2ui_tool import (
    GenerateA2UITool,
    _extract_json,
    _load_prompt,
)
from nexent.core.utils.observer import MessageObserver


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(content=next(self.responses))


def _tool(responses, *, surface_id=None, lang="zh"):
    model = FakeModel(responses)
    observer = MessageObserver(lang=lang)
    config = ModelConfig(
        cite_name="main", model_name="test", url="https://model.example"
    )
    tool = GenerateA2UITool(
        model_config=config,
        observer=observer,
        surface_id=surface_id,
        model_factory=lambda _config: model,
    )
    return tool, model, observer


def _valid_output(text="Hello"):
    return json.dumps(
        {
            "messages": [
                {
                    "updateComponents": {
                        "components": [
                            {"id": "root", "component": "Text", "text": text}
                        ]
                    }
                }
            ]
        }
    )


def test_declares_local_catalog_metadata():
    assert GenerateA2UITool.source == "local"
    assert getattr(GenerateA2UITool, "usage", None) is None


def test_default_model_factory_does_not_duplicate_stream_argument(mocker):
    model_class = mocker.patch("nexent.core.tools.generate_a2ui_tool.OpenAIModel")
    tool = GenerateA2UITool(
        model_config=ModelConfig(
            cite_name="main",
            model_name="test",
            url="https://model.example",
        ),
        observer=MessageObserver(),
    )

    assert tool._create_model() is model_class.return_value
    assert "stream" not in model_class.call_args.kwargs


@pytest.mark.parametrize("language", ["en", "zh"])
def test_generator_prompt_defines_operation_envelope_and_form_shape(language):
    prompt = _load_prompt(language)
    repair_prompt = prompt["repair_prompt"].format(
        error="invalid envelope",
        previous_output="{}",
    )

    assert set(prompt) == {"system_prompt", "user_prompt", "repair_prompt"}
    assert '{"messages":[{"updateComponents"' in prompt["system_prompt"]
    assert '"component":"Form"' in prompt["system_prompt"]
    assert '"action":{"event"' in prompt["system_prompt"]
    assert "Card" in prompt["system_prompt"] and '"child"' in prompt["system_prompt"]
    assert "Button" in prompt["system_prompt"] and '"action"' in prompt["system_prompt"]
    assert "text" in prompt["system_prompt"] and "label" in prompt["system_prompt"]
    assert '{"messages":[{"updateComponents"' in repair_prompt


@pytest.mark.parametrize(
    ("language", "expected_marker"),
    [
        ("zh", "描述："),
        ("zh-CN", "描述："),
        ("en", "Description:"),
        ("fr", "Description:"),
        (None, "Description:"),
    ],
)
def test_selects_prompt_language_from_observer(language, expected_marker):
    tool, model, _observer = _tool([_valid_output()], lang=language)

    tool.forward("Greeting", {}, "Greeting card")

    assert expected_marker in model.calls[0][0][1]["content"]


@pytest.mark.parametrize(
    ("raw_prompts", "expected_error"),
    [
        (None, "must be an object"),
        (
            {
                "system_prompt": "value",
                "user_prompt": "value",
                "repair_prompt": "",
            },
            "missing en.repair_prompt",
        ),
    ],
)
def test_prompt_loader_rejects_invalid_configuration(
    mocker, raw_prompts, expected_error
):
    mocker.patch(
        "nexent.core.tools.generate_a2ui_tool.yaml.safe_load", return_value=raw_prompts
    )

    with pytest.raises(ValueError, match=expected_error):
        _load_prompt()


def test_generates_server_surface_and_emits_isolated_a2ui_message():
    tool, model, observer = _tool([_valid_output()])
    result = json.loads(
        tool.forward("Show greeting", {"name": "Nexent"}, "Greeting card")
    )

    assert result["status"] == "rendered"
    assert result["surfaceId"].startswith("surface-")
    assert result["messageCount"] == 2
    assert len(model.calls) == 1
    assert model.calls[0][1]["response_format"] == {"type": "json_object"}
    emitted = [json.loads(item) for item in observer.message_query]
    assert len(emitted) == 2
    assert all(item["type"] == "a2ui" for item in emitted)
    envelope = json.loads(emitted[0]["content"])
    assert envelope["catalogId"] == "nexent.v1"
    assert envelope["message"]["createSurface"]["surfaceId"] == result["surfaceId"]


@pytest.mark.parametrize(
    ("language", "repair_marker"),
    [
        ("zh", "上一次生成的 JSON 未通过校验"),
        ("en", "The previous JSON failed validation"),
    ],
)
def test_repairs_once_and_updates_existing_surface(language, repair_marker):
    tool, model, observer = _tool(
        ["not json", _valid_output("Fixed")],
        surface_id="surface-existing",
        lang=language,
    )
    result = json.loads(tool.forward("Update", {}, "Updated surface"))

    assert result["surfaceId"] == "surface-existing"
    assert result["messageCount"] == 1
    assert len(model.calls) == 2
    assert repair_marker in model.calls[1][0][-1]["content"]
    envelope = json.loads(json.loads(observer.message_query[0])["content"])
    assert "createSurface" not in envelope["message"]


def test_repairs_component_contract_error_before_emitting_surface():
    invalid = json.dumps(
        {
            "messages": [
                {
                    "updateComponents": {
                        "components": [
                            {
                                "id": "root",
                                "component": "Card",
                                "children": ["title"],
                                "title": "Weather",
                            },
                            {"id": "title", "component": "Text", "text": "28°C"},
                        ]
                    }
                }
            ]
        }
    )
    tool, model, observer = _tool([invalid, _valid_output("Fixed weather")])

    result = json.loads(tool.forward("Weather", {}, "Weather card"))

    assert result["status"] == "rendered"
    assert len(model.calls) == 2
    assert "missing required properties: child" in model.calls[1][0][-1]["content"]
    assert len(observer.message_query) == 2


def test_second_validation_failure_is_tool_error_without_emission():
    tool, _model, observer = _tool(["bad", "still bad"])
    with pytest.raises(A2UIValidationError):
        tool.forward("Broken", {}, "Nothing")
    assert observer.message_query == []


def test_rejects_non_object_or_oversized_data():
    tool, _model, _observer = _tool([_valid_output()])
    with pytest.raises(ValueError, match="object"):
        tool.forward("Bad", [], "Nothing")
    with pytest.raises(ValueError, match="64 KiB"):
        tool.forward("Large", {"value": "x" * (64 * 1024)}, "Nothing")


def test_extract_json_removes_reasoning_and_markdown():
    assert _extract_json('<think>hidden</think>```json\n{"messages": []}\n```') == {
        "messages": []
    }
