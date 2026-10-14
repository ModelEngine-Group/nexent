import os
import stat

import pytest

from unittest.mock import Mock

from sdk.benchmark.tools.ctx_debugger import ContextDebugger, resolve_trace_path


def test_resolve_trace_path_creates_private_unique_files(monkeypatch):
    monkeypatch.delenv("NEXENT_CONTEXT_DEBUG", raising=False)

    open_file = Mock(wraps=os.open)
    monkeypatch.setattr(os, "open", open_file)
    first_path = resolve_trace_path("nexent_security_test_")
    second_path = resolve_trace_path("nexent_security_test_")

    try:
        assert first_path != second_path
        assert len(open_file.call_args_list) == 2
        assert all(call.args[2] == 0o600 for call in open_file.call_args_list)
        if os.name != "nt":
            assert stat.S_IMODE(os.stat(first_path).st_mode) == 0o600
            assert stat.S_IMODE(os.stat(second_path).st_mode) == 0o600
    finally:
        os.unlink(first_path)
        os.unlink(second_path)


def test_resolve_trace_path_preserves_explicit_environment_path(monkeypatch, tmp_path):
    configured_path = tmp_path / "configured.jsonl"
    monkeypatch.setenv("NEXENT_CONTEXT_DEBUG", str(configured_path))

    assert resolve_trace_path("ignored_") == str(configured_path)


def test_context_debugger_enforces_private_trace_permissions(tmp_path, monkeypatch):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("existing content", encoding="utf-8")
    trace_path.chmod(0o644)

    # Validate the POSIX permission request even on Windows, where fchmod is unavailable.
    fchmod = Mock(wraps=getattr(os, "fchmod", None))
    monkeypatch.setattr(os, "fchmod", fchmod, raising=False)
    ContextDebugger(str(trace_path), append=True)

    assert fchmod.call_count == 1
    assert fchmod.call_args.args[1] == 0o600
    if os.name != "nt":
        assert stat.S_IMODE(trace_path.stat().st_mode) == 0o600


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is unavailable")
def test_context_debugger_rejects_symbolic_link_trace_path(tmp_path):
    target_path = tmp_path / "target.jsonl"
    target_path.write_text("protected", encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    trace_path.symlink_to(target_path)

    with pytest.raises(OSError):
        ContextDebugger(str(trace_path))

    assert target_path.read_text(encoding="utf-8") == "protected"
