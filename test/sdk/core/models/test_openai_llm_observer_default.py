"""Regression tests for the default ``observer`` of ``OpenAIModel``.

``OpenAIModel.__init__`` used to default ``observer`` to the ``MessageObserver``
class object instead of an instance. Any caller that omitted ``observer`` then
crashed inside the streaming path with an unbound-method ``TypeError`` as soon
as the first token arrived - after the provider request had already been
billed. See https://github.com/ModelEngine-Group/nexent/issues/3921.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver, ProcessType


def _build_model(**overrides):
    """Construct a real OpenAIModel offline; no network call is made here."""
    kwargs = {
        "model_id": "gpt-4o-mini",
        "api_key": "sk-fake",
        "api_base": "https://example.invalid/v1",
    }
    kwargs.update(overrides)
    return OpenAIModel(**kwargs)


def _make_chunk(content, role=None):
    """Mimic the minimal shape of an OpenAI streaming chunk."""
    delta = SimpleNamespace(content=content, role=role)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(choices=[choice], usage=None)


def test_omitted_observer_defaults_to_instance():
    """The default observer must be a usable instance, not the class object."""
    model = _build_model()

    assert isinstance(model.observer, MessageObserver)
    assert model.observer is not MessageObserver


def test_each_model_gets_its_own_observer():
    """Omitting observer must not share one mutable instance across models."""
    first = _build_model()
    second = _build_model()

    assert first.observer is not second.observer


def test_explicit_observer_instance_is_preserved():
    """A caller-supplied observer must be stored as-is."""
    observer = MessageObserver(lang="en")

    model = _build_model(observer=observer)

    assert model.observer is observer


def test_explicit_none_observer_builds_instance():
    """Passing observer=None explicitly must behave like omitting it."""
    model = _build_model(observer=None)

    assert isinstance(model.observer, MessageObserver)


def test_streaming_call_without_observer_delivers_tokens():
    """Reproduce the issue: a call that omits observer must stream successfully.

    Before the fix this raised ``TypeError: MessageObserver.add_model_new_token()
    missing 1 required positional argument: 'new_token'``.
    """
    model = _build_model()
    chunks = [_make_chunk("Hello", role="assistant"), _make_chunk(" world")]

    with patch.object(
        model.client.chat.completions, "create", return_value=iter(chunks)
    ) as mock_create:
        message = model([{"role": "user", "content": "Say hello."}])

    mock_create.assert_called_once()
    assert message.content == "Hello world"

    # The default observer must have captured the streamed tokens as a
    # thinking-mode message so downstream consumers can render them.
    streamed = [json.loads(item) for item in model.observer.get_cached_message()]
    assert streamed, "default observer captured no streamed output"
    assert any(
        item["type"] == ProcessType.MODEL_OUTPUT_THINKING.value
        and "Hello world" in item["content"]
        for item in streamed
    )
