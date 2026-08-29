import threading
import time
from types import SimpleNamespace

import pytest

from nexent.memory.dreaming import (
    DreamingMemoryUnit,
    DreamingSummarizationRequest,
)
from services.memory_dreaming_summarizer import (
    TenantDreamingSummarizer,
    _load_prompt,
    _parse_summary_envelope,
)
from services import memory_dreaming_summarizer


@pytest.mark.parametrize("value", ["", "# User Memory", "<summary>x", "x<summary>y</summary>",
                                    "<summary></summary>",
                                    "<summary>a</summary><summary>b</summary>",
                                    "<summary><summary>x</summary></summary>"])
def test_ac056_rejects_malformed_envelope(value):
    with pytest.raises(ValueError):
        _parse_summary_envelope(value)


def test_ac056_parses_anchored_envelope():
    assert _parse_summary_envelope("<summary>\n## Project Preferences\n\n- x\n</summary>") == "## Project Preferences\n\n- x"


def _request(units, max_chars=1000):
    return DreamingSummarizationRequest(
        prior_markdown="## Existing Preference\n\n- old", prior_source="manual",
        new_evidence_markdown="new", units=units, max_chars=max_chars, attempt=1,
    )


def _summarizer(model, limit=10000):
    value = TenantDreamingSummarizer.__new__(TenantDreamingSummarizer)
    value.tenant_id = "t"
    value.user_id = "u"
    value.model = model
    value.prompt = _load_prompt()
    value.max_summarization_input_chars = limit
    return value


def test_ac078_constructor_requires_and_applies_tenant_model(monkeypatch):
    monkeypatch.setattr(
        memory_dreaming_summarizer.tenant_config_manager,
        "get_model_config",
        lambda **_kwargs: None,
    )
    with pytest.raises(RuntimeError):
        TenantDreamingSummarizer("t", "u")

    config = {
        "model_name": "test-model", "base_url": "http://model", "api_key": "secret",
        "max_input_tokens": 1000, "model_factory": "openai", "ssl_verify": False,
        "display_name": "Test", "timeout_seconds": 3,
    }
    model = object()
    monkeypatch.setattr(
        memory_dreaming_summarizer.tenant_config_manager,
        "get_model_config",
        lambda **_kwargs: config,
    )
    monkeypatch.setattr(memory_dreaming_summarizer, "OpenAIModel", lambda **_kwargs: model)
    monkeypatch.setattr(memory_dreaming_summarizer, "get_model_name_from_config", lambda _config: "test-model")

    summarizer = TenantDreamingSummarizer("t", "u")
    assert summarizer.model is model
    assert summarizer.max_summarization_input_chars == 20_000


def test_ac078_small_chunk_set_is_returned_without_repartitioning():
    units = [DreamingMemoryUnit(unit_id="1", content="new", is_new=True)]
    chunks = TenantDreamingSummarizer._chunk_units(_request(units), 100)
    assert len(chunks) == 2
    assert chunks[0].startswith("## Current Active User Memory")


def test_ac057_under_limit_uses_exactly_one_model_call():
    class Model:
        def __init__(self): self.calls = []
        def __call__(self, messages):
            self.calls.append(messages)
            return SimpleNamespace(content="<summary>## Work Preferences\n\n- old\n- new</summary>")
    model = Model()
    result = _summarizer(model)(_request([DreamingMemoryUnit(unit_id="u1", content="new", is_new=True)]))
    assert result.metadata["mode"] == "single"
    assert len(model.calls) == 1
    assert "Source: manual" in model.calls[0][1]["content"]
    assert "Output exactly one <summary>" in model.calls[0][0]["content"]
    assert "Task mode: single" in model.calls[0][1]["content"]


def test_ac058_large_input_map_reduce_is_bounded_parallel_and_ordered():
    lock = threading.Lock()
    active = maximum = 0
    reduce_prompt = ""
    task_modes = []

    class Model:
        def __call__(self, messages):
            nonlocal active, maximum, reduce_prompt
            prompt = messages[1]["content"]
            task_modes.append(next(line for line in prompt.splitlines() if line.startswith("Task mode:")))
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            with lock: active -= 1
            if "Map Summary" in prompt:
                reduce_prompt = prompt
                return SimpleNamespace(content="<summary>## Combined Preferences\n\n- final</summary>")
            marker = "".join(code for text, code in (("alpha", "A"), ("beta", "B"), ("charlie", "C")) if text in prompt) or "P"
            return SimpleNamespace(content=f"<summary>## Topic {marker}\n\n- {marker}</summary>")

    units = [DreamingMemoryUnit(unit_id=str(i), content=text * 20, is_new=True)
             for i, text in enumerate(("alpha", "beta", "charlie"), 1)]
    result = _summarizer(Model(), limit=100)(_request(units))
    assert result.metadata["mode"] == "map_reduce"
    assert result.metadata["chunk_count"] == 3
    assert maximum <= 3
    assert task_modes.count("Task mode: map") == 3
    assert task_modes.count("Task mode: reduce") == 1
    assert reduce_prompt.index("## Map Summary 1") < reduce_prompt.index("## Map Summary 2") < reduce_prompt.index("## Map Summary 3")
    assert reduce_prompt.index("- A") < reduce_prompt.index("- B") < reduce_prompt.index("C", reduce_prompt.index("- B"))
    assert result.markdown.endswith("- final")


def test_ac059_prompt_is_yaml_driven_and_forbids_json_and_evidence_ids():
    prompt = _load_prompt()
    assert prompt["output"]["format"] == "summary_envelope"
    assert "Do not output JSON" in prompt["system"]
    assert "evidence IDs" in prompt["system"]
    assert "no level-one heading" in prompt["system"]
    assert "Task mode: {task_mode}" in prompt["user"]
