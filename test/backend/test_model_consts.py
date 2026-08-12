import pytest
from pydantic import ValidationError

from backend.consts import model as model_consts


def test_model_connect_status_enum_defaults_and_get_value():
    assert model_consts.ModelConnectStatusEnum.get_default() == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value("") == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value(None) == "not_detected"
    assert model_consts.ModelConnectStatusEnum.get_value("available") == "available"


def test_model_request_and_validation():
    # Basic construction
    mr = model_consts.ModelRequest(model_name="mymodel", model_type="llm")
    assert mr.model_name == "mymodel"
    assert mr.model_type == "llm"

    # Chunk create request requires non-empty content
    with pytest.raises(ValidationError):
        model_consts.ChunkCreateRequest(content="")

    # Valid chunk create
    req = model_consts.ChunkCreateRequest(content="a", title="t", filename="f")
    assert req.content == "a"
    assert req.title == "t"
    assert req.filename == "f"


def test_skill_repository_install_request_limits_target_name_to_100_characters():
    request = model_consts.SkillRepositoryInstallRequest(target_name="x" * 100)
    assert len(request.target_name) == 100

    with pytest.raises(ValidationError):
        model_consts.SkillRepositoryInstallRequest(target_name="x" * 101)


def test_model_request_threads_w11_capacity_and_accept_fields():
    """W11 spec L721-727 + L500-502: ModelRequest must carry every capacity
    column the save handler can persist AND the audit-only accept-signal
    fields shipped by the frontend after a "Use suggestion" save. Pinning the
    field set here prevents a silent rename from dropping a column on the
    DB row or breaking the accept counter.
    """
    fields = set(model_consts.ModelRequest.model_fields.keys())
    required = {
        # W1/W2 capacity columns (persisted)
        "context_window_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "default_output_reserve_tokens",
        "tokenizer_family",
        "capacity_source",
        "capability_profile_version",
        # Canonical provider/model values
        "model_factory",
        "model_name",
        # Accept-signal audit fields (wire-only, stripped by app layer)
        "accepted_suggestion_match_kind",
        "accepted_capability_profile_version",
    }
    missing = required - fields
    assert not missing, f"ModelRequest missing W11 fields: {missing}"


@pytest.mark.parametrize(
    ("request_type", "required_fields"),
    [
        (
            model_consts.ManageTenantModelCreateRequest,
            {"tenant_id", "model_name", "model_type"},
        ),
        (
            model_consts.ManageTenantModelUpdateRequest,
            {"tenant_id", "current_display_name"},
        ),
    ],
)
def test_manage_model_requests_preserve_capacity_fields(request_type, required_fields):
    """Manage create/update must not silently discard capacity fields."""
    capacity_values = {
        "context_window_tokens": 128_000,
        "max_input_tokens": 120_000,
        "max_output_tokens": 8_000,
        "default_output_reserve_tokens": 4_000,
        "tokenizer_family": "cl100k_base",
        "capacity_source": "operator",
        "capability_profile_version": "2026-07-17",
    }
    required_values = {
        "tenant_id": "tenant-1",
        "model_name": "test-model",
        "model_type": "llm",
        "current_display_name": "Test Model",
    }
    request = request_type(
        **{
            field: required_values[field]
            for field in required_fields
        },
        **capacity_values,
    )

    dumped = request.model_dump(exclude_unset=True)
    assert {field: dumped[field] for field in capacity_values} == capacity_values


def test_capacity_suggestion_response_has_required_fields():
    """Pin ModelCapacitySuggestionResponse schema so a downstream rename
    (e.g. suggested_provider -> canonical_provider) trips a test instead
    of silently dropping the field from the API contract.
    """
    fields = set(model_consts.ModelCapacitySuggestionResponse.model_fields.keys())
    required = {
        "suggestions",
        "match_kind",
        "match_confidence",
        "match_explanation",
        "suggested_provider",
        "canonical_model_name",
        "capability_profile_version",
        "capacity_source_on_accept",
    }
    missing = required - fields
    assert not missing, (
        f"ModelCapacitySuggestionResponse missing W11 fields: {missing}"
    )


def test_filter_extra_params_passes_through_custom_object():
    """__custom__ sub-object is preserved regardless of model_type, alongside
    the existing allow-listed keys like enable_thinking."""
    result = model_consts.filter_extra_params(
        "llm",
        {"enable_thinking": True, "__custom__": {"my_key": "my_value"}},
    )
    assert result is not None
    assert result["enable_thinking"] is True
    assert result["__custom__"] == {"my_key": "my_value"}


def test_filter_extra_params_passes_through_custom_for_all_types():
    """__custom__ is type-agnostic: it survives for embedding/rerank/vlm too."""
    for model_type in ("embedding", "rerank", "vlm", "stt", "tts"):
        result = model_consts.filter_extra_params(
            model_type,
            {"__custom__": {"k1": "v1", "k2": "0.5"}},
        )
        assert result == {"__custom__": {"k1": "v1", "k2": "0.5"}}, (
            f"__custom__ should pass through for model_type={model_type}"
        )


def test_filter_extra_params_drops_invalid_custom_shape():
    """__custom__ must be a dict; non-dict values are dropped entirely."""
    result = model_consts.filter_extra_params("llm", {"__custom__": "not-a-dict"})
    assert result is None

    result = model_consts.filter_extra_params("llm", {"__custom__": ["list", "not", "dict"]})
    assert result is None


def test_filter_extra_params_drops_invalid_custom_entries():
    """Inside __custom__: non-string keys and non-primitive values are dropped
    individually; valid siblings survive."""
    result = model_consts.filter_extra_params(
        "llm",
        {"__custom__": {1: "int-key-dropped", "ok": "ok-value", "bad": {"nested": "dict"}}},
    )
    assert result == {"__custom__": {"ok": "ok-value"}}


def test_filter_extra_params_keeps_custom_alongside_allowed_keys():
    """__custom__ coexists with the type's allow-listed extra_params keys."""
    # LLM allows enable_thinking in extra_params; __custom__ rides alongside.
    result = model_consts.filter_extra_params(
        "llm",
        {"enable_thinking": False, "unknown_key": "dropped", "__custom__": {"x": "1"}},
    )
    assert result == {"enable_thinking": False, "__custom__": {"x": "1"}}


def test_filter_extra_params_drops_empty_custom():
    """An empty __custom__ dict (or all-invalid entries) yields no __custom__ key."""
    assert model_consts.filter_extra_params("llm", {"__custom__": {}}) is None
    assert model_consts.filter_extra_params(
        "llm", {"__custom__": {"bad": {"nested": "dict"}}}
    ) is None

