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

    # Chunk update request rejects empty content at the schema boundary
    with pytest.raises(ValidationError):
        model_consts.ChunkUpdateRequest(content="")

    # Update with omitted content is allowed (metadata-only fast path)
    upd = model_consts.ChunkUpdateRequest(title="new-title")
    assert upd.content is None
    assert upd.title == "new-title"


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


