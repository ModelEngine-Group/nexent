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

import json
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
                    # The loader normalizes each model entry into a
                    # ModelCatalogProfile instance; accept either the raw dict
                    # form or the normalized Pydantic model.
                    if isinstance(model_cfg, dict):
                        assert "model_type" in model_cfg
                    else:
                        assert getattr(model_cfg, "model_type", None)

    def test_openai_reasoning_presets_declare_supported_efforts(self):
        from configs.model_catalog_loader import get_model_profile

        expected_levels = {
            "o3": ["low", "medium", "high"],
            "o3-mini": ["low", "medium", "high"],
            "o4-mini": ["low", "medium", "high"],
            "gpt-5": ["minimal", "low", "medium", "high"],
            "gpt-5-mini": ["minimal", "low", "medium", "high"],
            "gpt-5.1": ["none", "low", "medium", "high"],
        }

        for model_name, levels in expected_levels.items():
            profile = get_model_profile("openai", model_name)
            assert profile is not None, f"Missing OpenAI preset: {model_name}"
            assert profile.reasoning_capability is not None
            assert profile.reasoning_capability.status == "supported"
            assert profile.reasoning_capability.control == "effort"
            assert profile.reasoning_capability.levels == levels
            assert profile.reasoning_capability.default in levels

    def test_major_vendor_reasoning_presets_declare_wire_formats(self):
        from configs.model_catalog_loader import get_model_profile

        expected = {
            ("deepseek", "deepseek-v4-pro"): (["low", "high", "max"], "reasoning_effort"),
            ("zhipu", "glm-4.7"): (["none", "high"], "thinking_toggle"),
            ("anthropic", "claude-sonnet-4-5-20250929"): (
                ["none", "low", "medium", "high"],
                "thinking_budget",
            ),
            ("google", "gemini-3.8-flash"): (["low", "medium", "high"], "reasoning_effort"),
            ("mistral", "mistral-medium-3-5"): (["none", "high"], "reasoning_effort"),
            ("xai", "grok-4.6"): (["low", "medium", "high", "xhigh"], "reasoning_effort"),
            ("dashscope", "qwen3.8-max"): (["low", "medium", "xhigh"], "reasoning_effort"),
            ("volcengine", "doubao-seed-2-1-pro-260628"): (["none", "high"], "thinking_toggle"),
        }

        for (provider, model_name), (levels, wire_format) in expected.items():
            profile = get_model_profile(provider, model_name)
            assert profile is not None, f"Missing preset: {provider}/{model_name}"
            assert profile.model_factory == provider
            assert profile.reasoning_capability is not None
            assert profile.reasoning_capability.levels == levels
            assert profile.reasoning_capability.wire_format == wire_format

        claude = get_model_profile("anthropic", "claude-sonnet-4-5-20250929")
        assert claude is not None
        assert claude.reasoning_capability is not None
        assert claude.reasoning_capability.effort_budgets == {
            "low": 2048,
            "medium": 8192,
            "high": 16384,
        }

    def test_historical_and_new_model_ids_use_conservative_reasoning_fallbacks(self):
        from configs.model_catalog_loader import resolve_reasoning_capability

        historical = resolve_reasoning_capability(
            "deepseek-reasoner", provider_hint="OpenAI-API-Compatible"
        )
        assert historical is not None
        assert historical["levels"] == ["low", "high", "max"]

        exact = resolve_reasoning_capability(
            "deepseek-v4-pro", provider_hint="deepseek"
        )
        assert exact is not None
        assert exact["default"] == "high"

        silicon_historical = resolve_reasoning_capability(
            "deepseek-reasoner", provider_hint="silicon"
        )
        assert silicon_historical is not None
        assert silicon_historical["default"] == "high"

        new_openai_id = resolve_reasoning_capability(
            "o3-pro", provider_hint="OpenAI-API-Compatible"
        )
        assert new_openai_id is not None
        assert new_openai_id["default"] == "medium"

        new_gpt_id = resolve_reasoning_capability(
            "gpt-5.1-unsupported", provider_hint="openai"
        )
        assert new_gpt_id is not None
        assert new_gpt_id["levels"] == ["minimal", "low", "medium", "high"]

        # An exact catalog entry with no reasoning declaration remains
        # explicitly unsupported; heuristics must not over-enable it.
        known_non_reasoning = resolve_reasoning_capability(
            "deepseek-ai/DeepSeek-R1", provider_hint="silicon"
        )
        assert known_non_reasoning is None

    @pytest.mark.parametrize(
        ("model_name", "provider_hint", "expected_wire_format"),
        [
            ("glm-4.99", "zhipu", "thinking_toggle"),
            ("claude-4.99-preview", "anthropic", "thinking_budget"),
            ("gemini-4-pro", "google", "reasoning_effort"),
            ("grok-4.99", "xai", "reasoning_effort"),
            ("qwen3.99-max", "dashscope", "reasoning_effort"),
            ("magistral-next", "mistral", "reasoning_effort"),
        ],
    )
    def test_unknown_vendor_model_ids_use_family_fallbacks(
        self, model_name, provider_hint, expected_wire_format
    ):
        from configs.model_catalog_loader import resolve_reasoning_capability

        capability = resolve_reasoning_capability(model_name, provider_hint=provider_hint)

        assert capability is not None
        assert capability["wire_format"] == expected_wire_format
        assert capability["status"] == "supported"

    @pytest.mark.parametrize(
        ("model_name", "expected_provider"),
        [
            ("claude-4.99-preview", "anthropic"),
            ("gemini-4-pro", "google"),
            ("grok-4.99", "xai"),
            ("glm-4.99", "zhipu"),
            ("qwen3.99-max", "dashscope"),
            ("mistral-large-next", "mistral"),
        ],
    )
    def test_model_id_inference_recognizes_known_vendors(self, model_name, expected_provider):
        from configs.model_catalog_loader import resolve_reasoning_capability

        capability = resolve_reasoning_capability(model_name)

        assert capability is not None
        if expected_provider == "zhipu":
            assert capability["control"] == "toggle"

    def test_empty_and_unknown_model_ids_have_no_capability(self):
        from configs.model_catalog_loader import resolve_reasoning_capability

        assert resolve_reasoning_capability("") is None
        assert resolve_reasoning_capability("unknown-model", provider_hint="custom") is None

    @pytest.mark.parametrize(
        ("model_name", "provider_hint"),
        [
            ("deepseek-v3-unsupported", "deepseek"),
            ("glm-4.0-unsupported", "zhipu"),
            ("claude-3-unsupported", "anthropic"),
            ("gemini-2.0-unsupported", "google"),
            ("gpt-4o-unsupported", "openai"),
            ("grok-3-unsupported", "xai"),
            ("qwen2.5-unsupported", "dashscope"),
            ("mistral-small-unsupported", "mistral"),
        ],
    )
    def test_vendor_fallbacks_leave_unsupported_families_disabled(
        self, model_name, provider_hint
    ):
        from configs.model_catalog_loader import resolve_reasoning_capability

        assert resolve_reasoning_capability(model_name, provider_hint=provider_hint) is None

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
            assert p.id
            assert p.display_name
            # At least one model per provider (otherwise why list it?)
            assert p.model_count
            assert p.model_count > 0

            # Spot-check: get a model profile and validate it
            from configs.model_catalog_loader import list_models_by_provider

            entries = list_models_by_provider(p.id)
            if entries:
                entry = entries[0]
                prof = get_model_profile(p.id, entry["model_name"])
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

class TestForcedTemperature:
    """forced_temperature: provider-enforced sampling default for reasoning models."""

    def _profile_via_loader(self, tmp_path: Path, forced_raw):
        import configs.model_catalog_loader as loader

        catalog = {
            "version": "9.9.9",
            "providers": {
                "prov": {
                    "display_name": "Prov",
                    "base_url": "https://prov.example.com/v1",
                    "models": {
                        "kimi-k3": {
                            "model_type": "llm",
                            "context_window_tokens": 1048576,
                            "max_output_tokens": 131072,
                            **({"forced_temperature": forced_raw} if forced_raw is not None else {}),
                        },
                    },
                },
            },
        }
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        with mock.patch.object(loader, "MODEL_CATALOG_JSON_PATH", str(path)):
            loader.load_model_catalog(force_reload=True)
            return loader.get_model_profile("prov", "kimi-k3")

    def test_profile_parses_forced_temperature(self, tmp_path: Path):
        profile = self._profile_via_loader(tmp_path, 1)
        assert profile is not None
        assert profile.forced_temperature == 1.0

    def test_profile_rejects_non_numeric_forced_temperature(self, tmp_path: Path):
        profile = self._profile_via_loader(tmp_path, "hot")
        assert profile is not None
        assert profile.forced_temperature is None

    def test_apply_catalog_defaults_fills_temperature(self, tmp_path: Path):
        import configs.model_catalog_loader as loader

        profile = self._profile_via_loader(tmp_path, 1)
        assert profile is not None

        user_data = {"model_name": "kimi-k3", "model_type": "llm"}
        applied = loader.apply_catalog_defaults(user_data, "prov")
        assert applied is True
        assert user_data["temperature"] == 1.0

    def test_apply_catalog_defaults_keeps_user_temperature(self, tmp_path: Path):
        import configs.model_catalog_loader as loader

        profile = self._profile_via_loader(tmp_path, 1)
        assert profile is not None

        user_data = {"model_name": "kimi-k3", "model_type": "llm", "temperature": 0.3}
        loader.apply_catalog_defaults(user_data, "prov")
        # A temperature the user explicitly set is never overridden.
        assert user_data["temperature"] == 0.3


class TestModelsDevReasoningResolution:
    """models.dev matching is scoped by API before model ID."""

    @staticmethod
    def _write_catalog(tmp_path: Path) -> Path:
        catalog = {
            "providers": {
                "deepseek": {
                    "api": "https://api.deepseek.com",
                    "models": {
                        "deepseek-v4-pro": {
                            "reasoning": True,
                            "reasoning_options": [
                                {"type": "toggle"},
                                {"type": "effort", "values": ["low", "high", "max"]},
                            ],
                        },
                    },
                },
                "siliconflow": {
                    "api": "https://api.siliconflow.com/v1",
                    "models": {
                        "deepseek-v4-pro": {
                            "reasoning": True,
                            "reasoning_options": [
                                {"type": "budget_tokens", "min": 128, "max": 32768},
                            ],
                        },
                    },
                },
                "alibaba-cn": {
                    "api": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "models": {
                        "qwen3.8-max": {
                            "reasoning": True,
                            "reasoning_options": [
                                {"type": "toggle"},
                                {"type": "effort", "values": ["low", "medium", "xhigh"]},
                                {"type": "budget_tokens", "min": 0, "max": 262144},
                            ],
                        },
                        "qwen3.7-plus": {
                            "reasoning": True,
                            "reasoning_options": [{"type": "budget_tokens", "max": 262144}],
                        },
                    },
                },
            }
        }
        path = tmp_path / "models-dev.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    def test_api_and_model_id_select_provider_specific_control(self, tmp_path: Path):
        import configs.model_catalog_loader as loader

        path = self._write_catalog(tmp_path)
        with mock.patch.object(loader, "MODELS_DEV_CATALOG_JSON_PATH", str(path)), mock.patch.object(
            loader, "_models_dev_cache", None
        ):
            deepseek = loader.resolve_reasoning_capability(
                "deepseek-v4-pro", "https://api.deepseek.com/", "OpenAI-API-Compatible"
            )
            silicon = loader.resolve_reasoning_capability(
                "deepseek-v4-pro", "https://api.siliconflow.com/v1", "OpenAI-API-Compatible"
            )
            qwen = loader.resolve_reasoning_capability(
                "qwen3.8-max", "https://dashscope.aliyuncs.com/compatible-mode/v1/", "alibaba-cn"
            )
            qwen_without_min = loader.resolve_reasoning_capability(
                "qwen3.7-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", "alibaba-cn"
            )

        assert deepseek is not None
        assert deepseek["source"] == "models_dev"
        assert {control["type"] for control in deepseek["controls"]} == {"toggle", "effort"}
        assert silicon is not None
        assert silicon["control"] == "budget_tokens"
        assert silicon["controls"] == [{"type": "budget_tokens", "min": 128, "max": 32768}]
        assert qwen is not None
        assert qwen["controls"] == [
            {"type": "toggle"},
            {"type": "effort", "values": ["low", "medium", "xhigh"]},
            {"type": "budget_tokens", "min": 0, "max": 262144},
        ]
        assert qwen_without_min is not None
        assert qwen_without_min["controls"] == [{"type": "budget_tokens", "min": 0, "max": 262144}]

    def test_budget_control_accepts_zero_minimum(self):
        from consts.model import ReasoningControl

        control = ReasoningControl(type="budget_tokens", min=0, max=262144)
        assert control.min == 0

    def test_existing_source_does_not_fall_back_to_model_name_heuristic(self, tmp_path: Path):
        import configs.model_catalog_loader as loader

        path = self._write_catalog(tmp_path)
        with mock.patch.object(loader, "MODELS_DEV_CATALOG_JSON_PATH", str(path)), mock.patch.object(
            loader, "_models_dev_cache", None
        ):
            capability = loader.resolve_reasoning_capability(
                "deepseek-reasoner", "https://api.deepseek.com", "OpenAI-API-Compatible"
            )

        assert capability is None

    def test_static_profile_uses_models_dev_provider_reasoning_controls(self, tmp_path: Path):
        import configs.model_catalog_loader as loader

        static_catalog = {
            "version": "1.0.0",
            "providers": {
                "zhipu": {
                    "display_name": "智谱",
                    "base_url": "https://open.bigmodel.cn/api/paas/v4/",
                    "model_factory": "zhipu",
                    "models": {
                        "glm-5.3": {
                            "model_type": "llm",
                            "reasoning_capability": {
                                "status": "supported",
                                "control": "toggle",
                                "levels": ["high"],
                                "default": "high",
                                "wire_format": "thinking_toggle",
                                "source": "catalog",
                            },
                        }
                    },
                }
            },
        }
        models_dev_catalog = {
            "providers": {
                "zhipuai": {
                    "api": "https://open.bigmodel.cn/api/paas/v4",
                    "models": {
                        "glm-5.3": {
                            "reasoning": True,
                            "reasoning_options": [
                                {"type": "effort", "values": ["low", "high", "max"]}
                            ],
                        }
                    },
                }
            }
        }
        static_path = tmp_path / "model-catalog.json"
        dev_path = tmp_path / "models-dev.json"
        static_path.write_text(json.dumps(static_catalog), encoding="utf-8")
        dev_path.write_text(json.dumps(models_dev_catalog), encoding="utf-8")

        with mock.patch.object(loader, "MODEL_CATALOG_JSON_PATH", str(static_path)), \
                mock.patch.object(loader, "MODELS_DEV_CATALOG_JSON_PATH", str(dev_path)), \
                mock.patch.object(loader, "_catalog_cache", None), \
                mock.patch.object(loader, "_models_dev_cache", None):
            profile = loader.get_model_profile("zhipu", "glm-5.3")

        assert profile is not None
        assert profile.reasoning_capability is not None
        assert profile.reasoning_capability.control == "effort"
        assert profile.reasoning_capability.levels == ["low", "high", "max"]
        assert profile.reasoning_capability.source == "models_dev"
