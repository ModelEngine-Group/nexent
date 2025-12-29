import sys
from pathlib import Path

# Ensure sdk/ is on sys.path so package imports resolve in the test environment
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk"))

from nexent.core.models.message_utils import _flatten_content, prepare_messages_for_completion
from types import SimpleNamespace


def test_flatten_string_returns_same():
    assert _flatten_content("hello") == "hello"


def test_flatten_none_returns_empty_string():
    assert _flatten_content(None) == ""


def test_flatten_number_returns_str():
    assert _flatten_content(123) == "123"


def test_flatten_list_with_various_items():
    data = ["a", 2, {"text": "b"}, {"content": 3}, {"other": "x"}]
    result = _flatten_content(data)
    # "a", "2", "b", "3", and str(dict) for the other dict should all appear concatenated
    assert result.startswith("a2b3")
    assert "other" in result or "x" in result


def test_flatten_list_with_non_dict_items_only():
    data = ["x", "y", 7]
    assert _flatten_content(data) == "xy7"


def test_prepare_messages_returns_unchanged_when_no_model_factory():
    obj = SimpleNamespace(role="user", content="hi")
    msgs = [obj]
    out = prepare_messages_for_completion(msgs, None)
    # Should return the same list object (unchanged)
    assert out is msgs


def test_prepare_messages_modelengine_with_objects_and_case_insensitive():
    obj1 = SimpleNamespace(role="system", content="SYS")
    obj2 = SimpleNamespace(role="user", content=["a", {"text": "b"}])
    prepared = prepare_messages_for_completion([obj1, obj2], "ModelEngine")
    assert isinstance(prepared, list)
    assert all(isinstance(x, dict) for x in prepared)
    assert prepared[0]["role"] == "system"
    assert "b" in prepared[1]["content"]


