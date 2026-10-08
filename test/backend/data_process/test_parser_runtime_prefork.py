import sys
import types
import os


def test_parser_runtime_initializes_core_inside_ensure(monkeypatch):
    from data_process import parser_runtime

    calls = []

    class FakeCore:
        def __init__(self, model_paths=None):
            calls.append(("init", model_paths))

        def preload_models(self, aliases):
            calls.append(("preload", aliases))

    fake_data_process = types.ModuleType("nexent.data_process")
    fake_data_process.DataProcessCore = FakeCore
    monkeypatch.setitem(sys.modules, "nexent.data_process", fake_data_process)
    monkeypatch.setattr(parser_runtime, "_configure_third_party_model_paths", lambda paths: paths)

    runtime = parser_runtime.ParserRuntime(thread_count=2, preload_models=["unstructured_default"])
    assert runtime.initialized is False
    runtime.ensure_initialized()

    assert runtime.initialized is True
    assert calls[0][0] == "init"
    assert calls[1] == ("preload", ["unstructured_default"])


def test_native_thread_limits_are_set_before_child_import(monkeypatch):
    from data_process.parser_runtime import _set_native_thread_limits

    _set_native_thread_limits(2)

    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        assert os.environ[name] == "2"
