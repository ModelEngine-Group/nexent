"""Formal model service relocation contracts."""

import ast
import importlib.util
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

pytestmark = [pytest.mark.case_id("MSRF-D1-002"), pytest.mark.stage("D1")]


ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / "backend/management/services/model"
MODULES = {
    "management",
    "provider",
    "health",
    "probe",
    "adapter",
    "resolver",
    "capacity",
    "reasoning",
    "names",
    "invocation",
}
OLD_SUFFIXES = {
    "model_management_service",
    "model_provider_service",
    "model_health_service",
    "model_capacity_suggestion_service",
    "model_gateway_service",
}
OLD_IMPORTS = {
    *("services." + name for name in OLD_SUFFIXES),
    "services." + "providers",
    *("utils." + name for name in ("model_name_utils", "llm_utils", "reasoning")),
}


def _python_sources(folder):
    """Avoid caches and local dependency directories."""
    for path in (ROOT / folder).rglob("*.py"):
        if not any(
            part in {".venv", "venv", "__pycache__"} or part.startswith("pytest-cache")
            for part in path.parts
        ):
            yield path


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def _load_pure(monkeypatch, path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_msrf_d1_002(monkeypatch):
    """MSRF-D1-002: retain signatures, dataclass defaults and name behavior."""
    snapshot = json.loads(
        (ROOT / "test/fixtures/model_refactor/signatures.json").read_text()
    )
    for expected in snapshot["functions"]:
        funcs = {
            n.name: n
            for n in _tree(MODEL / (expected["module"] + ".py")).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        actual = funcs[expected["name"]]
        assert isinstance(actual, ast.AsyncFunctionDef) == expected["async"]
        assert ast.dump(actual.args, include_attributes=False) == expected["args"], (
            expected["name"]
        )
        annotation = (
            ast.dump(actual.returns, include_attributes=False)
            if actual.returns
            else None
        )
        assert annotation == expected["returns"], expected["name"]

    contracts = _load_pure(
        monkeypatch, ROOT / "backend/contracts/model.py", "msrf_contracts"
    )
    assert contracts.ModelDescriptor().display_name == ""
    assert contracts.ModelDescriptor().is_multimodal is False
    assert vars(contracts.CapacitySuggestionFields()) == {
        "context_window_tokens": None,
        "max_input_tokens": None,
        "max_output_tokens": None,
        "default_output_reserve_tokens": None,
        "tokenizer_family": None,
    }
    assert [v.value for v in contracts.CapacitySuggestionMatchKind] == [
        "catalog_exact",
        "catalog_fuzzy",
        "provider_discovery",
        "litellm_lookup",
        "none",
    ]
    assert [v.value for v in contracts.CapacitySuggestionConfidence] == [
        "high",
        "medium",
        "low",
    ]
    with pytest.raises(FrozenInstanceError):
        contracts.ModelDescriptor().display_name = "changed"
    with pytest.raises(FrozenInstanceError):
        contracts.CapacitySuggestionFields().tokenizer_family = "changed"
    result = contracts.CapacitySuggestionResult(
        None, contracts.CapacitySuggestionMatchKind.NONE, None, "No match"
    )
    assert result.suggested_provider is None
    assert result.canonical_model_name is None
    assert result.capability_profile_version is None
    assert result.capacity_source_on_accept is None
    with pytest.raises(FrozenInstanceError):
        result.match_explanation = "changed"

    names = _load_pure(monkeypatch, MODEL / "names.py", "msrf_names")
    assert names.get_model_name_from_config(None) == ""
    assert names.get_model_name_from_config({}) == ""
    assert (
        names.get_model_name_from_config({"model_repo": "org", "model_name": "model"})
        == "org/model"
    )
    assert names.get_model_name_from_config({"modelName": "legacy"}) == "legacy"
    assert names.split_repo_name("org/sub/model") == ("org/sub", "model")
    assert names.add_repo_to_name("org", "org/model") == "org/model"
