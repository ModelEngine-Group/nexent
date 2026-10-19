import types

import httpx

from nexent.core.models.openai_llm import _resolve_openai_timeout_class


class CompatibleTimeout:
    """Minimal stand-in for the Timeout type owned by a patched OpenAI SDK."""

    def __init__(self, *, connect, read, write, pool):
        self.connect = connect
        self.read = read
        self.write = write
        self.pool = pool


def test_timeout_class_uses_openai_httpx2_backend_when_present():
    """A patched OpenAI client must receive its own httpx2 Timeout type."""
    base_client = types.SimpleNamespace(
        httpx2=types.SimpleNamespace(Timeout=CompatibleTimeout),
        httpx=types.SimpleNamespace(Timeout=httpx.Timeout),
    )

    assert _resolve_openai_timeout_class(base_client) is CompatibleTimeout


def test_timeout_class_uses_openai_httpx_backend_when_present():
    """The official OpenAI client must continue using its httpx Timeout type."""
    base_client = types.SimpleNamespace(
        httpx=types.SimpleNamespace(Timeout=httpx.Timeout),
    )

    assert _resolve_openai_timeout_class(base_client) is httpx.Timeout


def test_timeout_class_falls_back_to_standard_httpx():
    """Unknown OpenAI builds retain the standard httpx behavior."""
    assert _resolve_openai_timeout_class(types.SimpleNamespace()) is httpx.Timeout


def test_timeout_resolution_preserves_phase_specific_values():
    """Backend compatibility must not collapse the four timeout phases."""
    base_client = types.SimpleNamespace(
        httpx2=types.SimpleNamespace(Timeout=CompatibleTimeout),
    )
    timeout = _resolve_openai_timeout_class(base_client)(
        connect=11,
        read=45,
        write=31,
        pool=12,
    )

    assert isinstance(timeout, CompatibleTimeout)
    assert timeout.connect == 11
    assert timeout.read == 45
    assert timeout.write == 31
    assert timeout.pool == 12
