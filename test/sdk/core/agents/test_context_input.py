from types import SimpleNamespace

import pytest

from nexent.core.agents.context_input import ContextInput


def test_context_input_freezes_authorized_collections():
    component = SimpleNamespace(name="authorized-component")
    history = SimpleNamespace(role="user", content="authorized-history")

    snapshot = ContextInput(components=(component,), history=(history,))

    assert snapshot.components == (component,)
    assert snapshot.history == (history,)
    with pytest.raises(AttributeError):
        snapshot.components = ()


@pytest.mark.parametrize(
    ("components", "history"),
    [([], ()), ((), [])],
)
def test_context_input_rejects_mutable_collections(components, history):
    with pytest.raises(TypeError, match="immutable tuples"):
        ContextInput(components=components, history=history)
