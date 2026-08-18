"""Unit tests for backend.services.model_gateway_service.

Covers factory normalization, context construction, adapter resolution and
the VLM config-fetch helpers. Heavy database / utils / consts modules
are stubbed before import so only the gateway bridge logic is exercised.
"""

import os
import sys
from unittest import mock

import pytest

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)


class MockModule(mock.MagicMock):
    @classmethod
    def __getattr__(cls, key):
        return mock.MagicMock()  # Return a regular MagicMock instead of a new MockModule


# Mock required heavy modules before any import of the service occurs.
sys.modules['database'] = MockModule()
sys.modules['database.model_management_db'] = MockModule()
sys.modules['utils'] = MockModule()
sys.modules['utils.config_utils'] = MockModule()
sys.modules['consts'] = MockModule()
consts_const_module = MockModule()
consts_const_module.MODEL_CONFIG_MAPPING = {"vlm": "vlm_config_key", "vlm3": "vlm3_config_key"}
sys.modules['consts.const'] = consts_const_module

from nexent import MessageObserver
from nexent.core.gateway import VLMContext

from backend.services import model_gateway_service as mgs

# _normalize_factory


VOLC_CN = "\u706b\u5c71\u5f15\u64ce"  # volcengine CN alias
ALI_CN = "\u963f\u91cc\u4e91"  # alibaba CN alias


def test_normalize_factory_volc_aliases():
    with mock.patch.object(mgs, "get_registry") as mock_get_registry:
        mock_get_registry.return_value.has.return_value = True
        for raw in ("volc", "volcano", "volcengine", VOLC_CN, "  VOLC  "):
            assert mgs._normalize_factory(raw, "vlm") == "volc"
        for raw in ("ali", "alibaba", ALI_CN):
            assert mgs._normalize_factory(raw, "vlm") == "ali"
        assert mgs._normalize_factory("dashscope", "vlm") == "dashscope"


def test_normalize_factory_unknown_falls_back_to_modality_default():
    with mock.patch.object(mgs, "get_registry") as mock_get_registry:
        registry = mock_get_registry.return_value
        registry.has.return_value = False
        assert mgs._normalize_factory("", "llm") == "openai"
        assert mgs._normalize_factory(None, "llm") == "openai"
        assert mgs._normalize_factory("unknown", "llm") == "openai"
        assert mgs._normalize_factory("", "embedding") == "openai"
        assert mgs._normalize_factory("", "multi_embedding") == "jina"


def test_normalize_factory_registered_factory_passthrough():
    with mock.patch.object(mgs, "get_registry") as mock_get_registry:
        mock_get_registry.return_value.has.return_value = True
        assert mgs._normalize_factory("tokenpony", "llm") == "tokenpony"


# _coalesce


def test_coalesce_returns_first_non_none():
    assert mgs._coalesce(None, None, 3) == 3
    assert mgs._coalesce(None, "x") == "x"
    assert mgs._coalesce(None, None) is None


def test_coalesce_preserves_falsy_values():
    assert mgs._coalesce(0, 1) == 0
    assert mgs._coalesce(False, True) is False


# _config_to_context


def test_config_to_context_vlm_full_override():
    observer = mock.MagicMock()
    cfg = {
        "model_factory": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "ssl_verify": False,
        "display_name": "GPT-4o",
        "timeout_seconds": 9.5,
        "temperature": 0,
        "top_p": 0,
        "max_output_tokens": 128,
        "frequency_penalty": 0.4,
        "extra_body": {"max_completion_tokens": 200},
        "max_tokens": 64,
    }
    with mock.patch.object(mgs, "get_registry") as mock_get_registry:
        mock_get_registry.return_value.has.return_value = True
        ctx = mgs._config_to_context(
            cfg,
            "vlm",
            "vlm",
            "tenant-1",
            model_name="gpt-4o",
            capabilities={"video": False},
            observer=observer,
        )

    assert isinstance(ctx, VLMContext)
    assert ctx.model_name == "gpt-4o"
    assert ctx.base_url == "https://api.openai.com/v1"
    assert ctx.api_key == "sk-test"
    assert ctx.modality == "vlm"
    assert ctx.factory == "openai"
    assert ctx.tenant_id == "tenant-1"
    assert ctx.slot == "vlm"
    assert ctx.ssl_verify is False
    assert ctx.observer is observer
    assert ctx.display_name == "GPT-4o"
    assert ctx.timeout_seconds == 9.5
    assert ctx.temperature == 0
    assert ctx.top_p == 0
    assert ctx.max_output_tokens == 128
    assert ctx.frequency_penalty == 0.4
    assert ctx.extra_body == {"max_completion_tokens": 200}
    assert ctx.max_tokens == 64
    assert ctx.capabilities == {"video": False}


def test_config_to_context_cfg_none_uses_defaults_and_observer():
    with mock.patch.object(mgs, "get_registry") as mock_get_registry,             mock.patch.object(mgs, "get_model_name_from_config", return_value="repo/model"):
        mock_get_registry.return_value.has.return_value = False
        ctx = mgs._config_to_context(None, "vlm", "vlm", None)

    assert ctx.model_name == "repo/model"
    assert ctx.factory == "openai"
    assert ctx.base_url == ""
    assert ctx.api_key == ""
    assert ctx.ssl_verify is True
    assert isinstance(ctx.observer, MessageObserver)


def test_config_to_context_unknown_modality_raises():
    with mock.patch.object(mgs, "get_registry") as mock_get_registry:
        mock_get_registry.return_value.has.return_value = False
        with pytest.raises(ValueError, match="Unknown modality: foo"):
            mgs._config_to_context({}, "foo", "slot", None)


# Gateway / registry delegation


def test_get_adapter_from_config_delegates_to_gateway():
    gateway = mock.MagicMock()
    gateway.get_adapter.return_value = "adapter"
    with mock.patch.object(mgs, "get_gateway", return_value=gateway):
        result = mgs.get_adapter_from_config({"model_factory": "openai"}, "vlm", "vlm", "t1", temperature=0)

    assert result == "adapter"
    gateway.get_adapter.assert_called_once()
    ctx = gateway.get_adapter.call_args.args[0]
    assert isinstance(ctx, VLMContext)
    assert ctx.tenant_id == "t1"
    assert ctx.temperature == 0


def test_build_adapter_fresh_constructs_without_gateway_cache():
    dummy_class = mock.MagicMock()
    with mock.patch.object(mgs, "get_registry") as mock_get_registry:
        mock_get_registry.return_value.has.return_value = True
        mock_get_registry.return_value.resolve.return_value = dummy_class
        result = mgs.build_adapter_fresh({"model_factory": "openai"}, "vlm", "vlm", "t1")

    assert result == dummy_class.return_value
    dummy_class.assert_called_once()
    assert dummy_class.call_args.args[0].factory == "openai"


# _fetch_slot_config


def test_fetch_slot_config_by_model_id():
    cfg = {"model_type": "vlm"}
    with mock.patch.object(mgs, "get_model_by_model_id", return_value=cfg) as mock_get_model:
        assert mgs._fetch_slot_config("t1", 5, "vlm", "vlm") is cfg
    mock_get_model.assert_called_once_with(5, "t1")


def test_fetch_slot_config_model_not_found_raises():
    with mock.patch.object(mgs, "get_model_by_model_id", return_value=None), \
            pytest.raises(ValueError, match="Model not found: 5"):
        mgs._fetch_slot_config("t1", 5, "vlm", "vlm")


def test_fetch_slot_config_wrong_model_type_raises():
    with mock.patch.object(mgs, "get_model_by_model_id", return_value={"model_type": "llm"}), \
            pytest.raises(ValueError, match="not a vlm model"):
        mgs._fetch_slot_config("t1", 5, "vlm", "vlm")


def test_fetch_slot_config_by_slot_key():
    tenant_config_manager = mock.MagicMock()
    cfg = {"model_type": "vlm"}
    tenant_config_manager.get_model_config.return_value = cfg
    with mock.patch.object(mgs, "tenant_config_manager", tenant_config_manager):
        assert mgs._fetch_slot_config("t1", None, "vlm", "vlm") is cfg
    tenant_config_manager.get_model_config.assert_called_once_with(key="vlm_config_key", tenant_id="t1")


# Public entry points


def test_get_vlm_adapter_from_config_delegates():
    with mock.patch.object(mgs, "get_adapter_from_config", return_value="adapter") as mock_delegate:
        result = mgs.get_vlm_adapter_from_config({"a": 1}, "t1", "vlm3", temperature=0.3)

    assert result == "adapter"
    mock_delegate.assert_called_once_with({"a": 1}, "vlm", "vlm3", "t1", temperature=0.3)


def test_get_vlm_adapter_returns_adapter():
    gateway = mock.MagicMock()
    gateway.get_adapter.return_value = "adapter"
    cfg = {"model_factory": "openai", "model_type": "vlm"}
    with mock.patch.object(mgs, "_fetch_slot_config", return_value=cfg) as mock_fetch,             mock.patch.object(mgs, "get_gateway", return_value=gateway):
        result = mgs.get_vlm_adapter("t1", 5, "vlm")

    assert result == "adapter"
    mock_fetch.assert_called_once_with("t1", 5, expected_type="vlm", slot_key="vlm")
    gateway.get_adapter.assert_called_once()
    assert gateway.get_adapter.call_args.args[0].slot == "vlm"


def test_get_vlm_adapter_returns_none_without_config():
    with mock.patch.object(mgs, "_fetch_slot_config", return_value=None):
        assert mgs.get_vlm_adapter("t1", None) is None
