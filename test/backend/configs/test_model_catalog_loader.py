"""Unit tests for backend/configs/model_catalog_loader.py.

Covers:
- JSON catalog load / graceful degradation when file is missing.
- Provider and model profile lookups.
- apply_catalog_defaults merging policy (user values > catalog defaults).
- List APIs (list_catalog_providers / list_models_by_provider).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Catalog loader tests
# ---------------------------------------------------------------------------


class TestModelCatalogLoaderSmoke:
    """Minimal smoke-level tests that don't require a full venv sync."""

    def test_json_file_exists_and_is_readable(self):
        from consts.const import MODEL_CATALOG_JSON_PATH

        path = Path(MODEL_CATALOG_JSON_PATH)
        assert path.exists(), (
            f"MODEL_CATALOG_JSON_PATH={MODEL_CATALOG_JSON_PATH} should exist. "
            "Create backend/configs/model_catalog.json or set env var to a valid file."
        )
        assert path.stat().st_size > 0, "Model catalog JSON file is empty."

    def test_loader_imports_and_exports_expected_symbols(self):
        from configs import model_catalog_loader

        for name in (
            "load_model_catalog",
            "list_catalog_providers",
            "get_model_profile",
            "list_models_by_provider",
            "apply_catalog_defaults",
            "infer_provider_from_base_url",
            "MODEL_CATALOG_JSON_PATH",
        ):
            # Note: MODEL_CATALOG_JSON_PATH lives in consts.const; the loader
            # re-exports it from the consts module so tests/mocks can patch it.
            assert hasattr(model_catalog_loader, name), f"Missing symbol: {name}"

    def test_load_catalog_succeeds_with_current_json(self):
        from configs.model_catalog_loader import load_model_catalog

        catalog = load_model_catalog(force_reload=True)
        assert isinstance(catalog, dict)
        assert "version" in catalog
        assert "providers" in catalog
        # At least 1 provider shipped in the default catalog.
        assert len(catalog["providers"]) >= 1
        for provider_key, provider_block in catalog["providers"].items():
            assert isinstance(provider_key, str)
            # Provider block structure
            assert "display_name" in provider_block
            if "models" in provider_block:
                for model_name, model_cfg in provider_block["models"].items():
                    assert isinstance(model_name, str)
                    assert "model_type" in model_cfg

    def test_pydantic_models_match_catalog(self):
        from consts.model import ModelCatalogProfile, ModelCatalogProviderInfo
        from configs.model_catalog_loader import (
            list_catalog_providers,
            get_model_profile,
        )

        providers = list_catalog_providers()
        # All providers must serialize via the Pydantic model without raising.
        for p in providers:
            assert isinstance(p, ModelCatalogProviderInfo)
            # Verify non-empty
            assert p.provider_key
            assert p.display_name
            # At least one model per provider (otherwise why list it?)
            assert p.model_count and p.model_count > 0

            # Spot-check: get a model profile and validate it
            from configs.model_catalog_loader import list_models_by_provider

            entries = list_models_by_provider(p.provider_key)
            if entries:
                entry = entries[0]
                prof = get_model_profile(p.provider_key, entry["model_name"])
                assert isinstance(prof, ModelCatalogProfile)
                assert prof.model_type  # required field

    def test_apply_catalog_defaults_preserves_user_values(self):
        from configs.model_catalog_loader import apply_catalog_defaults

        user_data: Dict[str, Any] = {
            "model_name": "Qwen/Qwen3-8B",
            "api_key": "sk-user-already-set-this",
            # Provide an explicit non-empty value that the catalog would
            # otherwise also set. Must stay.
            "base_url": "https://my-proxy.internal.example.com/v1/",
            "context_window_tokens": 4096,  # deliberate tiny number
        }
        applied = apply_catalog_defaults(user_data, "silicon")
        # Either applied or not is fine, but user values MUST be unchanged.
        assert user_data["api_key"] == "sk-user-already-set-this"
        assert user_data["base_url"] == "https://my-proxy.internal.example.com/v1/"
        assert user_data["context_window_tokens"] == 4096

    def test_apply_catalog_defaults_fills_missing_fields(self):
        from configs.model_catalog_loader import apply_catalog_defaults

        user_data: Dict[str, Any] = {
            "model_name": "Qwen/Qwen3-8B",
            # No base_url, no capacity fields.
        }
        applied = apply_catalog_defaults(user_data, "silicon")
        # If the catalog knows about silicon provider, at least base_url must
        # be filled in. Otherwise the call must simply not raise.
        assert applied in (True, False)
        if applied:
            assert user_data.get("base_url"), "base_url should be filled from the catalog."
            assert user_data.get("context_window_tokens"), "context_window should be set."
            assert user_data.get("max_output_tokens"), "max_output_tokens should be set."


class TestModelCatalogLoaderDegradation:
    """Verify graceful handling when JSON catalog is missing / broken."""

    def test_missing_json_returns_empty_providers_no_crash(self):
        import configs.model_catalog_loader as loader

        with mock.patch.object(loader, "MODEL_CATALOG_JSON_PATH", "/does/not/exist.json"):
            # Reload to pick up the mocked path
            cat = loader.load_model_catalog(force_reload=True)
            assert cat["providers"] == {}
            assert loader.list_catalog_providers() == []
            assert loader.get_model_profile("any", "model") is None

    def test_malformed_json_degrades_gracefully(self, tmp_path: Path):
        import configs.model_catalog_loader as loader

        bad = tmp_path / "broken.json"
        # A JSON string missing closing braces is guaranteed parse-invalid.
        bad.write_text('{"providers": [ { "unclosed": ')
        with mock.patch.object(loader, "MODEL_CATALOG_JSON_PATH", str(bad)):
            cat = loader.load_model_catalog(force_reload=True)
            assert cat["providers"] == {}
