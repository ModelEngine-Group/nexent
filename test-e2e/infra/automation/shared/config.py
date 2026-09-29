from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def test_root() -> Path:
    configured = os.environ.get("NEXENT_TEST_HOME", "").strip()
    if not configured:
        raise RuntimeError("NEXENT_TEST_HOME must name a machine-local test data directory")
    return Path(configured).resolve()


# Imported helpers must never be collected as test functions by pytest.
test_root.__test__ = False


def repo_root() -> Path:
    configured = os.environ.get("NEXENT_REPO", "").strip()
    root = Path(configured).resolve() if configured else Path(__file__).resolve().parents[4]
    if not (root / "test-e2e/cases").is_dir():
        raise RuntimeError("NEXENT_REPO must point to the Nexent checkout containing test-e2e")
    return root


def load_yaml(name: str) -> dict[str, Any]:
    value = yaml.safe_load((test_root() / "config" / name).read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"config/{name} must contain a mapping")
    return value


def load_secret_env() -> dict[str, str]:
    result: dict[str, str] = {}
    path = test_root() / "config" / "secrets.env"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def service_url(name: str) -> str:
    env = load_yaml("environment.yaml")
    explicit = {
        "config": "NEXENT_CONFIG_URL",
        "runtime": "NEXENT_RUNTIME_URL",
        "northbound": "NEXENT_NORTHBOUND_URL",
        "data_process": "NEXENT_DATA_PROCESS_URL",
    }
    defaults = {
        "config": "http://localhost:5010",
        "runtime": "http://localhost:5014",
        "northbound": "http://localhost:5013",
        "data_process": "http://localhost:5012",
    }
    if name not in explicit:
        raise KeyError(name)
    configured = env.get("services", {}).get(name, {}).get("url") if isinstance(env.get("services"), dict) else None
    return str(os.environ.get(explicit[name]) or configured or defaults[name]).rstrip("/")


def controlled_asset_url(path: str = "") -> str:
    """Return a URL served by the batch-scoped controlled asset service."""
    base = (
        os.environ.get("NEXENT_TEST_ASSETS_URL", "").strip()
        or os.environ.get("NEXENT_TEST_ASSETS_CONTAINER_URL", "").strip()
    )
    if not base:
        raise RuntimeError(
            "NEXENT_TEST_ASSETS_URL is required for controlled HTTP assets; "
            "start services/test-assets/server.py through the test runner"
        )
    suffix = str(path or "").strip()
    if not suffix:
        return base.rstrip("/")
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


def model_by_type(model_type: str) -> dict[str, Any]:
    models = load_yaml("models.yaml").get("models", [])
    for model in models:
        configured_type = model.get("type") or model.get("capability") or model.get("model_type")
        if str(configured_type or "").lower() == model_type.lower():
            return model
    raise RuntimeError(f"models.yaml has no {model_type!r} model")
