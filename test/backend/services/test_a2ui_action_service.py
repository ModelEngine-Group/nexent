import json

import pytest

from consts.model import A2UIActionSubmission
from services.a2ui_action_service import (
    A2UIActionDuplicateError,
    A2UIActionValidationError,
    ValidatedA2UIAction,
    _build_validated_payload,
    _find_action_name,
    _find_surface_component,
    _normalize_form_values,
    _project_form,
    build_a2ui_action_label,
    release_a2ui_action_reservation,
    validate_a2ui_action_submission,
)
from utils.a2ui_action_utils import (
    build_a2ui_action_query,
    normalize_legacy_a2ui_action_text,
    project_a2ui_submission_state,
    sanitize_a2ui_action_label,
)

_NO_FORM = object()


def test_action_display_helpers_handle_empty_and_legacy_values():
    assert sanitize_a2ui_action_label(None) is None
    assert sanitize_a2ui_action_label("\x00\u200b") is None
    assert (
        normalize_legacy_a2ui_action_text("[A2UI action] submit_feedback (root)", "en")
        == "Perform action"
    )
    assert (
        normalize_legacy_a2ui_action_text("normal question", "zh") == "normal question"
    )
    assert normalize_legacy_a2ui_action_text({"text": "unchanged"}) == {
        "text": "unchanged"
    }


@pytest.mark.parametrize(
    ("component", "action_name", "language", "expected"),
    [
        ({"component": "Form", "submitLabel": "提交"}, "submit", "zh", "提交"),
        ({"component": "Form"}, "submit", "zh", "Submit"),
        (
            {
                "component": "ApprovalCard",
                "approveLabel": "同意",
                "approveAction": {"event": {"name": "approve"}},
            },
            "approve",
            "zh",
            "同意",
        ),
        (
            {
                "component": "ApprovalCard",
                "rejectAction": {"event": {"name": "reject"}},
            },
            "reject",
            "en",
            "Reject",
        ),
        (
            {"component": "Button", "_resolvedActionLabel": "Download report"},
            "download",
            "en",
            "Download report",
        ),
        (
            {"component": "Button", "_resolvedActionLabel": {"path": "/dynamic"}},
            "run",
            "zh",
            "执行操作",
        ),
        ({"component": "Unknown"}, "run", "en", "Perform action"),
    ],
)
def test_build_a2ui_action_label_uses_authoritative_component(
    component, action_name, language, expected
):
    validated = ValidatedA2UIAction(payload={}, component=component)

    assert (
        build_a2ui_action_label(
            validated,
            action_name=action_name,
            language=language,
        )
        == expected
    )


def test_build_a2ui_action_label_sanitizes_and_limits_literal_label():
    validated = ValidatedA2UIAction(
        payload={},
        component={
            "component": "Button",
            "_resolvedActionLabel": "  Download\n\x00report  " + "x" * 300,
        },
    )

    label = build_a2ui_action_label(
        validated,
        action_name="download",
        language="en",
    )

    assert label.startswith("Download report")
    assert "\n" not in label
    assert "\x00" not in label
    assert len(label) == 256


def _submission(*, form_values=_NO_FORM, **action_overrides):
    action = {
        "name": "approve",
        "surfaceId": "surface-1",
        "sourceComponentId": "approval",
        "timestamp": "2026-07-27T10:00:00Z",
        "context": {"decision": True},
        **action_overrides,
    }
    payload = {
        "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
        "message": {"version": "v0.9", "action": action},
    }
    if form_values is not _NO_FORM:
        payload["formSubmission"] = {"values": form_values}
    return A2UIActionSubmission.model_validate(payload)


def _history(action_name="approve"):
    envelope = {
        "protocolVersion": "v0.9",
        "catalogId": "nexent.v1",
        "surfaceId": "surface-1",
        "message": {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": "surface-1",
                "components": [
                    {
                        "id": "approval",
                        "component": "Button",
                        "action": {"event": {"name": action_name, "context": {}}},
                    }
                ],
            },
        },
    }
    return {
        "message_records": [
            {"units": [{"unit_type": "a2ui", "unit_content": json.dumps(envelope)}]}
        ]
    }


def _form_history(fields=None):
    history = _history("submit_form")
    history["message_records"][0]["units"][0]["unit_content"] = json.dumps(
        {
            "surfaceId": "surface-1",
            "message": {
                "updateComponents": {
                    "components": [
                        {
                            "id": "approval",
                            "component": "Form",
                            "title": "Profile",
                            "fields": fields
                            or [
                                {
                                    "name": "name",
                                    "label": "Name",
                                    "type": "text",
                                    "required": True,
                                },
                                {"name": "notes", "label": "Notes", "type": "textarea"},
                                {"name": "age", "label": "Age", "type": "number"},
                                {
                                    "name": "room",
                                    "label": "Room",
                                    "type": "select",
                                    "options": [{"label": "Suite", "value": "suite"}],
                                },
                                {
                                    "name": "confirmed",
                                    "label": "Confirmed",
                                    "type": "checkbox",
                                },
                                {"name": "date", "label": "Date", "type": "date"},
                            ],
                            "submitLabel": "Save",
                            "action": {"event": {"name": "submit_form", "context": {}}},
                        }
                    ]
                }
            },
        }
    )
    return history


def test_valid_action_checks_ownership_surface_and_idempotency(monkeypatch):
    redis = type("Redis", (), {"set": lambda self, *args, **kwargs: True})()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: _history()
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    validate_a2ui_action_submission(_submission(), conversation_id=7, user_id="user-1")


def test_action_and_surface_lookup_tolerate_historical_noise():
    assert _find_action_name({"action": {"name": "direct"}}) == "direct"
    assert (
        _find_action_name(
            {"children": [{"nested": {"action": {"event": {"name": "event"}}}}]}
        )
        == "event"
    )
    assert _find_action_name({"children": ["none"]}) is None

    history = {
        "message_records": [
            {
                "units": [
                    {"unit_type": "text", "unit_content": "ignored"},
                    {"unit_type": "a2ui", "unit_content": "not-json"},
                    {"unit_type": "a2ui", "unit_content": []},
                    {"unit_type": "a2ui", "unit_content": {"surfaceId": "other"}},
                    {
                        "unit_type": "a2ui",
                        "unit_content": {"surfaceId": "surface-1", "message": {}},
                    },
                    {
                        "unit_type": "a2ui",
                        "unit_content": {
                            "surfaceId": "surface-1",
                            "message": {"updateComponents": {"components": "invalid"}},
                        },
                    },
                    {
                        "unit_type": "a2ui",
                        "unit_content": {
                            "surfaceId": "surface-1",
                            "message": {
                                "updateComponents": {
                                    "components": [
                                        {
                                            "id": "approval",
                                            "component": "Button",
                                            "action": {"name": "approve"},
                                        }
                                    ]
                                }
                            },
                        },
                    },
                ]
            }
        ]
    }
    assert _find_surface_component(history, "surface-1", "approval")["id"] == "approval"


def test_surface_lookup_uses_latest_component_definition():
    history = _history("approve")
    history["message_records"].append(_history("reject")["message_records"][0])

    component = _find_surface_component(history, "surface-1", "approval")

    assert component["action"]["event"]["name"] == "reject"


def test_surface_lookup_resolves_button_child_text():
    history = _history("download")
    envelope = json.loads(history["message_records"][0]["units"][0]["unit_content"])
    components = envelope["message"]["updateComponents"]["components"]
    components[0]["child"] = "download-label"
    components.append(
        {
            "id": "download-label",
            "component": "Text",
            "text": "Download report",
        }
    )
    history["message_records"][0]["units"][0]["unit_content"] = json.dumps(envelope)

    component = _find_surface_component(history, "surface-1", "approval")

    assert component["_resolvedActionLabel"] == "Download report"


def test_rejects_action_removed_by_latest_component_definition(monkeypatch):
    history = _history("approve")
    history["message_records"].append(_history("reject")["message_records"][0])
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: history
    )

    with pytest.raises(A2UIActionValidationError, match="does not match"):
        validate_a2ui_action_submission(
            _submission(name="approve"),
            conversation_id=7,
            user_id="user-1",
        )


@pytest.mark.parametrize(
    ("component", "action_name"),
    [
        (
            {
                "component": "ApprovalCard",
                "approveAction": {"event": {"name": "approve"}},
                "rejectAction": {"event": {"name": "reject"}},
            },
            "reject",
        ),
    ],
)
def test_validates_catalog_action_properties(monkeypatch, component, action_name):
    history = _history(action_name)
    history["message_records"][0]["units"][0]["unit_content"] = json.dumps(
        {
            "surfaceId": "surface-1",
            "message": {
                "updateComponents": {
                    "components": [{"id": "approval", **component}],
                }
            },
        }
    )
    redis = type("Redis", (), {"set": lambda self, *args, **kwargs: True})()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: history
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    validate_a2ui_action_submission(
        _submission(name=action_name),
        conversation_id=7,
        user_id="user-1",
    )


def test_validates_and_normalizes_form_submission(monkeypatch):
    redis = type("Redis", (), {"set": lambda self, *args, **kwargs: True})()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history",
        lambda *_: _form_history(),
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    result = validate_a2ui_action_submission(
        _submission(
            name="submit_form",
            form_values={
                "name": "Ada",
                "notes": "",
                "age": 30,
                "room": "suite",
                "date": "2026-08-01",
            },
        ),
        conversation_id=7,
        user_id="user-1",
    )

    form_submission = result.payload["formSubmission"]
    assert form_submission["form"] == {
        "id": "approval",
        "component": "Form",
        "title": "Profile",
        "fields": [
            {"name": "name", "label": "Name", "type": "text", "required": True},
            {"name": "notes", "label": "Notes", "type": "textarea"},
            {"name": "age", "label": "Age", "type": "number"},
            {
                "name": "room",
                "label": "Room",
                "type": "select",
                "options": [{"label": "Suite", "value": "suite"}],
            },
            {"name": "confirmed", "label": "Confirmed", "type": "checkbox"},
            {"name": "date", "label": "Date", "type": "date"},
        ],
        "submitLabel": "Save",
        "action": {"event": {"name": "submit_form", "context": {}}},
    }
    assert form_submission["values"] == {
        "name": "Ada",
        "notes": None,
        "age": 30,
        "room": "suite",
        "confirmed": False,
        "date": "2026-08-01",
    }


@pytest.mark.parametrize(
    ("form_values", "error"),
    [
        ({"name": "Ada", "unknown": "x"}, "undeclared"),
        ({}, "required"),
        ({"name": "Ada", "age": True}, "finite"),
        ({"name": "Ada", "room": "standard"}, "not declared"),
        ({"name": "Ada", "confirmed": "yes"}, "boolean"),
        ({"name": "Ada", "date": "2026-02-30"}, "YYYY-MM-DD"),
    ],
)
def test_rejects_invalid_form_values_before_idempotency(
    monkeypatch, form_values, error
):
    redis_calls = []
    redis = type(
        "Redis", (), {"set": lambda self, *args, **kwargs: redis_calls.append(args)}
    )()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history",
        lambda *_: _form_history(),
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    with pytest.raises(A2UIActionValidationError, match=error):
        validate_a2ui_action_submission(
            _submission(name="submit_form", form_values=form_values),
            conversation_id=7,
            user_id="user-1",
        )
    assert redis_calls == []


def test_form_submission_component_contract_is_strict(monkeypatch):
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history",
        lambda *_: _form_history(),
    )
    with pytest.raises(A2UIActionValidationError, match="require formSubmission"):
        validate_a2ui_action_submission(
            _submission(name="submit_form"), conversation_id=7, user_id="user-1"
        )

    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: _history()
    )
    with pytest.raises(A2UIActionValidationError, match="only valid"):
        validate_a2ui_action_submission(
            _submission(form_values={}), conversation_id=7, user_id="user-1"
        )


def test_rejects_duplicate_form_fields_and_large_values(monkeypatch):
    duplicate_fields = [
        {"name": "name", "label": "Name", "type": "text"},
        {"name": "name", "label": "Again", "type": "text"},
    ]
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history",
        lambda *_: _form_history(duplicate_fields),
    )
    with pytest.raises(A2UIActionValidationError, match="unique"):
        validate_a2ui_action_submission(
            _submission(name="submit_form", form_values={"name": "Ada"}),
            conversation_id=7,
            user_id="user-1",
        )

    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history",
        lambda *_: _form_history(),
    )
    with pytest.raises(A2UIActionValidationError, match="64 KiB"):
        validate_a2ui_action_submission(
            _submission(name="submit_form", form_values={"name": "x" * (64 * 1024)}),
            conversation_id=7,
            user_id="user-1",
        )


@pytest.mark.parametrize(
    ("component", "error"),
    [
        ({"component": "Form", "fields": "bad"}, "invalid fields"),
        ({"component": "Form", "fields": ["bad"]}, "invalid field"),
        (
            {
                "component": "Form",
                "fields": [{"name": "x", "label": 1, "type": "text"}],
            },
            "definition",
        ),
        (
            {
                "component": "Form",
                "fields": [
                    {"name": "x", "label": "X", "type": "select", "options": "bad"}
                ],
            },
            "options",
        ),
        (
            {
                "component": "Form",
                "fields": [
                    {"name": "x", "label": "X", "type": "select", "options": [{}]}
                ],
            },
            "options",
        ),
    ],
)
def test_rejects_invalid_persisted_form_definitions(component, error):
    with pytest.raises(A2UIActionValidationError, match=error):
        _project_form(component)


def test_form_value_edge_cases_and_payload_limits():
    assert _normalize_form_values(
        {"text": None, "number": None},
        [
            {"name": "text", "type": "text"},
            {"name": "number", "type": "number"},
        ],
    ) == {"text": None, "number": None}

    cases = [
        ({"value": []}, [{"name": "value", "type": "text"}], "string"),
        (
            {"value": " "},
            [{"name": "value", "type": "text", "required": True}],
            "empty",
        ),
        ({"value": "20260728"}, [{"name": "value", "type": "date"}], "YYYY-MM-DD"),
        (
            {"value": False},
            [{"name": "value", "type": "checkbox", "required": True}],
            "selected",
        ),
        ({"value": {"bad"}}, [{"name": "value", "type": "text"}], "JSON primitives"),
    ]
    for values, fields, error in cases:
        with pytest.raises(A2UIActionValidationError, match=error):
            _normalize_form_values(values, fields)

    with pytest.raises(A2UIActionValidationError, match="256 KiB"):
        _build_validated_payload(
            _submission(name="submit_form", form_values={"value": "ok"}),
            {
                "id": "approval",
                "component": "Form",
                "fields": [
                    {"name": "value", "label": "x" * (256 * 1024), "type": "text"}
                ],
                "action": {"event": {"name": "submit_form", "context": {}}},
            },
        )


def test_rejects_unserializable_action_payload(monkeypatch):
    def fail_serialization(_payload):
        raise ValueError("invalid")

    monkeypatch.setattr(
        "services.a2ui_action_service.serialize_a2ui_action_payload",
        fail_serialization,
    )
    with pytest.raises(A2UIActionValidationError, match="valid JSON"):
        _build_validated_payload(
            _submission(),
            {"id": "approval", "component": "Button"},
        )


def test_action_query_rejects_incomplete_payloads():
    with pytest.raises(ValueError, match="message.action"):
        build_a2ui_action_query({})
    with pytest.raises(ValueError, match="identity"):
        build_a2ui_action_query({"message": {"action": {}}})


@pytest.mark.parametrize(
    ("submission", "conversation_id", "history", "error"),
    [
        (_submission(), None, _history(), "existing conversation"),
        (_submission(), 7, None, "not accessible"),
        (_submission(timestamp="not-a-date"), 7, _history(), "ISO-8601"),
        (_submission(sourceComponentId="missing"), 7, _history(), "not found"),
        (_submission(name="reject"), 7, _history(), "does not match"),
    ],
)
def test_rejects_invalid_action(
    monkeypatch, submission, conversation_id, history, error
):
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: history
    )
    with pytest.raises(A2UIActionValidationError, match=error):
        validate_a2ui_action_submission(
            submission,
            conversation_id=conversation_id,
            user_id="user-1",
        )


def test_rejects_large_context(monkeypatch):
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: _history()
    )
    with pytest.raises(A2UIActionValidationError, match="64 KiB"):
        validate_a2ui_action_submission(
            _submission(context={"value": "x" * (64 * 1024)}),
            conversation_id=7,
            user_id="user-1",
        )


@pytest.mark.parametrize(
    "redis",
    [
        None,
        type(
            "BrokenRedis",
            (),
            {"set": lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError())},
        )(),
    ],
)
def test_rejects_unavailable_idempotency_store(monkeypatch, redis):
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: _history()
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)
    with pytest.raises(A2UIActionValidationError, match="idempotency"):
        validate_a2ui_action_submission(
            _submission(), conversation_id=7, user_id="user-1"
        )


def test_rejects_duplicate_submission(monkeypatch):
    redis = type("Redis", (), {"set": lambda self, *args, **kwargs: False})()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: _history()
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)
    with pytest.raises(A2UIActionDuplicateError, match="already submitted"):
        validate_a2ui_action_submission(
            _submission(), conversation_id=7, user_id="user-1"
        )


def _accepted_form_payload():
    history = _form_history()
    component = _find_surface_component(history, "surface-1", "approval")
    return _build_validated_payload(
        _submission(
            name="submit_form",
            form_values={"name": "Ada", "room": "suite"},
        ),
        component,
    )


def test_projects_only_safe_form_submission_state():
    payload = _accepted_form_payload()

    assert project_a2ui_submission_state(payload) == {
        "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
        "surfaceId": "surface-1",
        "sourceComponentId": "approval",
        "status": "accepted",
    }
    assert project_a2ui_submission_state({"formSubmission": {}}) is None
    assert "Ada" not in json.dumps(
        project_a2ui_submission_state(payload), ensure_ascii=False
    )


def test_rejects_form_already_accepted_in_hidden_history(monkeypatch):
    history = _form_history()
    history["message_records"].append(
        {
            "units": [
                {
                    "unit_type": "a2ui_action",
                    "unit_content": json.dumps(_accepted_form_payload()),
                }
            ]
        }
    )
    redis_calls = []
    redis = type(
        "Redis", (), {"set": lambda self, *args, **kwargs: redis_calls.append(args)}
    )()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: history
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    with pytest.raises(A2UIActionDuplicateError, match="Form was already"):
        validate_a2ui_action_submission(
            _submission(
                name="submit_form",
                form_values={"name": "Grace", "room": "suite"},
            ),
            conversation_id=7,
            user_id="user-1",
        )
    assert redis_calls == []


def test_form_submission_on_a_new_surface_is_independent(monkeypatch):
    history = _form_history()
    history["message_records"].append(
        {
            "units": [
                {
                    "unit_type": "a2ui_action",
                    "unit_content": json.dumps(_accepted_form_payload()),
                }
            ]
        }
    )
    second_surface = _form_history()["message_records"][0]
    second_envelope = json.loads(second_surface["units"][0]["unit_content"])
    second_envelope["surfaceId"] = "surface-2"
    second_surface["units"][0]["unit_content"] = json.dumps(second_envelope)
    history["message_records"].append(second_surface)
    redis = type("Redis", (), {"set": lambda self, *args, **kwargs: True})()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history", lambda *_: history
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    result = validate_a2ui_action_submission(
        _submission(
            name="submit_form",
            surfaceId="surface-2",
            form_values={"name": "Grace", "room": "suite"},
        ),
        conversation_id=7,
        user_id="user-1",
    )

    assert result.payload["message"]["action"]["surfaceId"] == "surface-2"
    assert result.payload["formSubmission"]["values"]["name"] == "Grace"


def test_form_redis_reservation_blocks_concurrent_submission_and_rolls_back_id(
    monkeypatch,
):
    calls = []
    deleted = []

    class Redis:
        def set(self, key, value, **kwargs):
            calls.append((key, value, kwargs))
            return len(calls) == 1

        def delete(self, *keys):
            deleted.extend(keys)

    redis = Redis()
    monkeypatch.setattr(
        "services.a2ui_action_service.get_conversation_history",
        lambda *_: _form_history(),
    )
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)

    with pytest.raises(A2UIActionDuplicateError, match="Form was already"):
        validate_a2ui_action_submission(
            _submission(
                name="submit_form",
                form_values={"name": "Ada", "room": "suite"},
            ),
            conversation_id=7,
            user_id="user-1",
        )

    assert len(calls) == 2
    assert ":form-submitted:user-1:7:surface-1:approval" in calls[1][0]
    assert isinstance(calls[1][1], str)
    assert deleted == [calls[0][0]]


def test_releases_all_action_reservations(monkeypatch):
    deleted = []
    redis = type("Redis", (), {"delete": lambda self, *keys: deleted.extend(keys)})()
    monkeypatch.setattr("services.a2ui_action_service.get_redis_client", lambda: redis)
    validated = ValidatedA2UIAction(
        payload={},
        component={},
        reservation_keys=("submission", "form"),
    )

    release_a2ui_action_reservation(validated)

    assert deleted == ["submission", "form"]
