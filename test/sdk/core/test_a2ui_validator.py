import pytest

from nexent.core.a2ui.validator import (
    A2UI_CATALOG_ID,
    A2UIValidationError,
    validate_a2ui_messages,
)


def _messages(components=None, data=None):
    messages = []
    if data is not None:
        messages.append({"updateDataModel": {"path": "/", "value": data}})
    messages.append(
        {
            "updateComponents": {
                "components": components
                or [{"id": "root", "component": "Text", "text": "Hello"}]
            }
        }
    )
    return messages


def _form_messages():
    components = [
        {
            "id": "root",
            "component": "Card",
            "child": "form-column",
        },
        {
            "id": "form-column",
            "component": "Column",
            "children": [
                "title",
                "name",
                "notes",
                "age",
                "role",
                "confirmed",
                "date",
                "divider",
                "submit",
            ],
        },
        {"id": "title", "component": "Text", "text": "Feedback", "variant": "h2"},
        {
            "id": "name",
            "component": "TextField",
            "label": "Name",
            "value": {"path": "/form/name"},
            "variant": "shortText",
        },
        {
            "id": "notes",
            "component": "TextField",
            "label": "Notes",
            "value": {"path": "/form/notes"},
            "variant": "longText",
        },
        {
            "id": "age",
            "component": "TextField",
            "label": "Age",
            "value": {"path": "/form/age"},
            "variant": "number",
        },
        {
            "id": "role",
            "component": "ChoicePicker",
            "label": "Role",
            "options": [
                {"label": "Engineer", "value": "engineer"},
                {"label": "Designer", "value": "designer"},
            ],
            "value": {"path": "/form/role"},
            "variant": "mutuallyExclusive",
        },
        {
            "id": "confirmed",
            "component": "CheckBox",
            "label": "Confirmed",
            "value": {"path": "/form/confirmed"},
        },
        {
            "id": "date",
            "component": "DateTimeInput",
            "label": "Date",
            "value": {"path": "/form/date"},
            "enableDate": True,
            "enableTime": False,
        },
        {"id": "divider", "component": "Divider"},
        {
            "id": "submit",
            "component": "Button",
            "child": "submit-label",
            "variant": "primary",
            "action": {
                "event": {
                    "name": "submit_form",
                    "context": {
                        "name": {"path": "/form/name"},
                        "notes": {"path": "/form/notes"},
                        "age": {"path": "/form/age"},
                        "role": {"path": "/form/role"},
                        "confirmed": {"path": "/form/confirmed"},
                        "date": {"path": "/form/date"},
                    },
                }
            },
        },
        {"id": "submit-label", "component": "Text", "text": "Submit"},
    ]
    data = {
        "form": {
            "name": "",
            "notes": "",
            "age": "",
            "role": [],
            "confirmed": False,
            "date": "",
        }
    }
    return _messages(components, data)


def test_normalizes_official_catalog_surface_and_all_basic_form_fields():
    result = validate_a2ui_messages({"messages": _form_messages()}, surface_id="surface-1")

    assert result[0] == {
        "version": "v0.9",
        "createSurface": {"surfaceId": "surface-1", "catalogId": A2UI_CATALOG_ID},
    }
    assert A2UI_CATALOG_ID == "https://a2ui.org/specification/v0_9/basic_catalog.json"
    assert result[1]["updateDataModel"] == {
        "surfaceId": "surface-1",
        "path": "/",
        "value": _form_messages()[0]["updateDataModel"]["value"],
    }
    assert result[2]["updateComponents"]["surfaceId"] == "surface-1"
    component_types = {
        component["component"]
        for component in result[2]["updateComponents"]["components"]
    }
    assert {
        "Text",
        "Button",
        "Card",
        "Column",
        "Divider",
        "TextField",
        "CheckBox",
        "ChoicePicker",
        "DateTimeInput",
    } <= component_types


def test_accepts_row_layout_bindings_and_literal_action_context():
    components = [
        {"id": "root", "component": "Row", "children": ["text", "button"]},
        {"id": "text", "component": "Text", "text": {"path": "/message"}},
        {
            "id": "button",
            "component": "Button",
            "child": "button-label",
            "action": {
                "event": {
                    "name": "continue",
                    "context": {"count": 1, "enabled": True, "items": ["a"]},
                }
            },
        },
        {"id": "button-label", "component": "Text", "text": "Continue"},
    ]

    result = validate_a2ui_messages(_messages(components, {"message": "Ready"}), surface_id="surface-1")

    assert result[-1]["updateComponents"]["components"] == components


@pytest.mark.parametrize("component_type", ["Form", "DataTable", "Chart", "ApprovalCard", "ArtifactCard"])
def test_rejects_custom_catalog_components(component_type):
    with pytest.raises(A2UIValidationError, match="outside the supported basic catalog"):
        validate_a2ui_messages(
            _messages([{"id": "root", "component": component_type}]),
            surface_id="surface-1",
        )


@pytest.mark.parametrize(
    ("component", "error"),
    [
        ({"id": "root", "component": "Text", "text": "x", "style": {}}, "unsupported properties"),
        ({"id": "root", "component": "Text", "text": "<script>x</script>"}, "HTML"),
        ({"id": "root", "component": "Text", "text": "javascript:alert(1)"}, "HTML"),
        ({"id": "root", "component": "Text", "text": 1}, "string or data binding"),
        ({"id": "root", "component": "Text", "text": "x", "variant": "hero"}, "variant"),
        ({"id": "root", "component": "Divider", "axis": "diagonal"}, "axis"),
        ({"id": "root", "component": "Column", "children": [], "align": "left"}, "align"),
        ({"id": "root", "component": "Row", "children": [], "justify": "left"}, "justify"),
        (
            {"id": "root", "component": "TextField", "label": "Name", "variant": "email"},
            "variant",
        ),
        (
            {"id": "root", "component": "CheckBox", "label": "Yes", "value": "yes"},
            "boolean or data binding",
        ),
        (
            {"id": "root", "component": "ChoicePicker", "options": [], "value": []},
            "non-empty",
        ),
        (
            {
                "id": "root",
                "component": "DateTimeInput",
                "value": "",
                "enableDate": "yes",
            },
            "must be a boolean",
        ),
    ],
)
def test_rejects_invalid_basic_component_contracts(component, error):
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(_messages([component]), surface_id="surface-1")


@pytest.mark.parametrize(
    ("action", "error"),
    [
        ({}, "exactly one event"),
        ({"event": "run"}, "unsupported properties"),
        ({"event": {"name": ""}}, "name is invalid"),
        ({"event": {"name": "run", "target": "api"}}, "unsupported properties"),
        ({"event": {"name": "run", "context": []}}, "must be an object"),
        ({"event": {"name": "run", "context": {"nested": {"value": 1}}}}, "literals or data bindings"),
    ],
)
def test_rejects_invalid_button_actions(action, error):
    components = [
        {
            "id": "root",
            "component": "Button",
            "child": "label",
            "action": action,
        },
        {"id": "label", "component": "Text", "text": "Run"},
    ]
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(_messages(components), surface_id="surface-1")


def test_rejects_missing_references_root_cycles_and_duplicate_ids():
    with pytest.raises(A2UIValidationError, match="Unknown component references"):
        validate_a2ui_messages(
            _messages([{"id": "root", "component": "Column", "children": ["missing"]}]),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="root"):
        validate_a2ui_messages(
            _messages([{"id": "other", "component": "Text", "text": "x"}]),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="cycle"):
        validate_a2ui_messages(
            _messages([{"id": "root", "component": "Column", "children": ["root"]}]),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="unique"):
        validate_a2ui_messages(
            _messages(
                [
                    {"id": "root", "component": "Text", "text": "one"},
                    {"id": "root", "component": "Text", "text": "two"},
                ]
            ),
            surface_id="surface-1",
        )


def test_rejects_depth_component_action_and_message_size_limits():
    chain = [
        {
            "id": "root" if index == 0 else f"node-{index}",
            "component": "Column",
            "children": [f"node-{index + 1}"] if index < 16 else [],
        }
        for index in range(17)
    ]
    with pytest.raises(A2UIValidationError, match="depth 16"):
        validate_a2ui_messages(_messages(chain), surface_id="surface-1")

    components = [{"id": "root", "component": "Column", "children": []}]
    components.extend(
        {"id": f"item-{index}", "component": "Text", "text": "x"}
        for index in range(200)
    )
    with pytest.raises(A2UIValidationError, match="200 components"):
        validate_a2ui_messages(_messages(components), surface_id="surface-1")

    action_components = [
        {
            "id": "root",
            "component": "Button",
            "child": "label",
            "action": {"event": {"name": "run", "context": {"value": "x" * (64 * 1024)}}},
        },
        {"id": "label", "component": "Text", "text": "Run"},
    ]
    with pytest.raises(A2UIValidationError, match="Action context"):
        validate_a2ui_messages(_messages(action_components), surface_id="surface-1")

    with pytest.raises(A2UIValidationError, match="256 KiB"):
        validate_a2ui_messages(
            _messages([{"id": "root", "component": "Text", "text": "x" * (256 * 1024)}]),
            surface_id="surface-1",
        )


@pytest.mark.parametrize(
    ("raw", "surface_id", "error"),
    [
        ({"invalid": True}, "surface-1", "messages array"),
        ([], "surface-1", "non-empty"),
        (_messages(), "unsafe surface", "Invalid server-generated surface id"),
        (["bad"], "surface-1", "must be an object"),
        ([{"version": "v1.0", "updateDataModel": {"value": {}}}], "surface-1", "version"),
        ([{"createSurface": {}}], "surface-1", "unsupported operation"),
        ([{"updateComponents": "bad"}], "surface-1", "contain only components"),
        ([{"updateComponents": {"components": []}}], "surface-1", "non-empty array"),
        ([{"updateComponents": {"components": ["bad"]}}], "surface-1", "must be objects"),
        ([{"updateDataModel": {"path": "bad", "value": {}}}], "surface-1", "JSON Pointer"),
        ([{"updateDataModel": {"path": "/"}}], "surface-1", "value is required"),
        (
            [{"updateComponents": {"components": [{"id": "unsafe id", "component": "Text"}]}}],
            "surface-1",
            "safe id",
        ),
    ],
)
def test_rejects_malformed_messages(raw, surface_id, error):
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(raw, surface_id=surface_id)
