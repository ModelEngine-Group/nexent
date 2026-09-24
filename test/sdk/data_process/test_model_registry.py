import sys
import types


def test_model_registry_loads_alias_only_on_first_access(monkeypatch):
    from nexent.data_process.model_registry import ModelRegistry

    calls = []

    def get_model():
        calls.append("loaded")
        return object()

    base_module = types.ModuleType("unstructured_inference.models.base")
    base_module.get_model = get_model
    models_module = types.ModuleType("unstructured_inference.models")
    models_module.__path__ = []
    inference_module = types.ModuleType("unstructured_inference")
    inference_module.__path__ = []
    monkeypatch.setitem(sys.modules, "unstructured_inference", inference_module)
    monkeypatch.setitem(sys.modules, "unstructured_inference.models", models_module)
    monkeypatch.setitem(sys.modules, "unstructured_inference.models.base", base_module)

    registry = ModelRegistry({"unstructured_default": None})
    assert calls == []
    model = registry.get("unstructured_default")
    assert model is registry.get("unstructured_default")
    assert calls == ["loaded"]


def test_model_registry_rejects_unknown_preload_alias():
    from nexent.data_process.model_registry import ModelRegistry

    try:
        ModelRegistry().validate_aliases(["does_not_exist"])
    except ValueError as exc:
        assert "does_not_exist" in str(exc)
    else:
        raise AssertionError("unknown model alias was accepted")


def test_model_registry_accepts_empty_model_paths_until_model_access():
    from nexent.data_process.model_registry import ModelRegistry

    registry = ModelRegistry({"unstructured_default": None, "table_transformer": None})

    assert registry.model_paths == {"unstructured_default": None, "table_transformer": None}
