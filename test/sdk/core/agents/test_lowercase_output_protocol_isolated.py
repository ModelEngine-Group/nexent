"""Exercise the output protocol without importing unrelated Nexent services."""

import importlib.util
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def protocol(monkeypatch):
    for name in ("nexent", "nexent.core", "nexent.core.agents"):
        module = types.ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    clarification = types.ModuleType("nexent.core.agents.clarification")
    clarification.CLARIFICATION_SCHEMA_GUIDANCE = ""
    clarification.ClarificationForm = type("ClarificationForm", (), {})
    monkeypatch.setitem(sys.modules, clarification.__name__, clarification)
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "nexent.core.agents.output_protocol", root / "sdk/nexent/core/agents/output_protocol.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_lowercase_final_answer_is_accepted(protocol):
    answer = protocol.classify_model_output("<final_answer>ok</final_answer>", protocol="final_envelope")
    assert answer.answer == "ok"


def test_uppercase_final_answer_is_rejected(protocol):
    with pytest.raises(protocol.ModelOutputProtocolError):
        protocol.classify_model_output("<FINAL_ANSWER>old</FINAL_ANSWER>", protocol="final_envelope")


def test_uppercase_legacy_run_is_rejected_even_after_code_label(protocol):
    with pytest.raises(protocol.ModelOutputProtocolError):
        protocol.classify_model_output("Code: ```<RUN>print(1)```", protocol="code_action")
