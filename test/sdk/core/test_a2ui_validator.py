import pytest

from nexent.core.a2ui.validator import A2UIValidationError, validate_a2ui_messages


def _components(*extra):
    return [
        {
            "id": "root",
            "component": "Column",
            "children": ["title", *[item["id"] for item in extra]],
        },
        {"id": "title", "component": "Text", "text": "Safe title"},
        *extra,
    ]


def _messages(components=None):
    return [
        {
            "updateComponents": {
                "surfaceId": "model-value-is-rewritten",
                "components": components or _components(),
            }
        }
    ]


def test_normalizes_surface_and_catalog():
    result = validate_a2ui_messages(_messages(), surface_id="surface-1")
    assert result[0] == {
        "version": "v0.9",
        "createSurface": {"surfaceId": "surface-1", "catalogId": "nexent.v1"},
    }
    assert result[1]["updateComponents"]["surfaceId"] == "surface-1"


def test_accepts_business_components_and_trusted_urls():
    components = _components(
        {
            "id": "artifact",
            "component": "ArtifactCard",
            "title": "Report",
            "url": "https://objects.example.com/report.pdf",
        },
        {
            "id": "form",
            "component": "Form",
            "fields": [{"name": "date", "label": "Date", "type": "date"}],
            "action": {
                "event": {"name": "submit", "context": {"date": {"path": "/form/date"}}}
            },
        },
    )
    result = validate_a2ui_messages(
        {"messages": _messages(components)},
        surface_id="surface-1",
        allowed_url_hosts=["objects.example.com"],
    )
    assert len(result) == 2


@pytest.mark.parametrize(
    ("components", "error"),
    [
        (_components({"id": "bad", "component": "Arbitrary"}), "outside nexent.v1"),
        (
            _components(
                {"id": "bad", "component": "Text", "html": "<script>x</script>"}
            ),
            "Forbidden",
        ),
        (
            _components(
                {"id": "bad", "component": "Image", "url": "javascript:alert(1)"}
            ),
            "javascript",
        ),
        (
            _components(
                {"id": "bad", "component": "Image", "url": "http://example.com/a"}
            ),
            "HTTPS",
        ),
        (
            _components({"id": "bad", "component": "Image", "url": "//evil.example/a"}),
            "HTTPS",
        ),
        (
            _components(
                {"id": "bad", "component": "Image", "url": "https://evil.example/a"}
            ),
            "not trusted",
        ),
        (
            _components(
                {"id": "bad", "component": "Chart", "chartType": "scatter", "data": []}
            ),
            "chartType",
        ),
        (
            _components(
                {"id": "bad", "component": "Form", "fields": [{"type": "email"}]}
            ),
            "unsupported",
        ),
        (_components({"id": "bad", "component": "Text", "style": {}}), "Forbidden"),
        (
            _components({"id": "title", "component": "Text", "text": "duplicate"}),
            "unique",
        ),
    ],
)
def test_rejects_catalog_and_security_violations(components, error):
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(_messages(components), surface_id="surface-1")


def test_rejects_reference_cycle_missing_reference_and_missing_root():
    with pytest.raises(A2UIValidationError, match="cycle"):
        validate_a2ui_messages(
            _messages([{"id": "root", "component": "Column", "children": ["root"]}]),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="Unknown"):
        validate_a2ui_messages(
            _messages([{"id": "root", "component": "Column", "children": ["missing"]}]),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="root"):
        validate_a2ui_messages(
            _messages([{"id": "title", "component": "Text", "text": "x"}]),
            surface_id="surface-1",
        )


def test_rejects_size_and_collection_limits():
    with pytest.raises(A2UIValidationError, match="500"):
        validate_a2ui_messages(
            _messages(
                _components(
                    {"id": "table", "component": "DataTable", "rows": [{}] * 501}
                )
            ),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="1000"):
        validate_a2ui_messages(
            _messages(
                _components(
                    {
                        "id": "chart",
                        "component": "Chart",
                        "chartType": "line",
                        "data": [{}] * 1001,
                    }
                )
            ),
            surface_id="surface-1",
        )
    with pytest.raises(A2UIValidationError, match="200"):
        validate_a2ui_messages(
            _messages(
                [
                    {"id": "root", "component": "Column", "children": []},
                    *[
                        {"id": f"item-{index}", "component": "Text", "text": "x"}
                        for index in range(200)
                    ],
                ]
            ),
            surface_id="surface-1",
        )


def test_update_existing_surface_and_data_model():
    result = validate_a2ui_messages(
        [
            _messages()[0],
            {"updateDataModel": {"path": "/value", "value": {"safe": True}}},
        ],
        surface_id="surface-1",
        create_surface=False,
    )
    assert "createSurface" not in result[0]
    assert result[1]["updateDataModel"]["surfaceId"] == "surface-1"


def test_accepts_relative_url_string_reference_and_ignores_model_create_surface():
    result = validate_a2ui_messages(
        [
            {"createSurface": {"surfaceId": "model"}},
            {
                "updateComponents": {
                    "components": [
                        {"id": "root", "component": "Card", "child": "image"},
                        {
                            "id": "image",
                            "component": "Image",
                            "url": "/api/assets/image.png",
                        },
                    ]
                }
            },
        ],
        surface_id="surface-1",
    )
    assert len(result) == 2


def test_accepts_renderable_weather_card_component_contract():
    components = [
        {"id": "root", "component": "Card", "child": "weather"},
        {
            "id": "weather",
            "component": "Column",
            "children": ["title", "temperature", "refresh"],
        },
        {"id": "title", "component": "Text", "text": "Today's weather"},
        {"id": "temperature", "component": "Text", "text": "28°C"},
        {
            "id": "refresh",
            "component": "Button",
            "child": "refresh-label",
            "action": {"event": {"name": "refresh_weather", "context": {}}},
        },
        {"id": "refresh-label", "component": "Text", "text": "Refresh"},
    ]

    result = validate_a2ui_messages(_messages(components), surface_id="surface-1")

    assert result[1]["updateComponents"]["components"] == components


@pytest.mark.parametrize(
    ("component", "error"),
    [
        (
            {
                "id": "root",
                "component": "Card",
                "children": ["content"],
                "title": "Weather",
            },
            "missing required properties: child",
        ),
        (
            {
                "id": "root",
                "component": "Button",
                "text": "Refresh",
                "action": {"event": {"name": "refresh", "context": {}}},
            },
            "missing required properties: child",
        ),
        (
            {"id": "root", "component": "Column", "children": [], "spacing": "8px"},
            "unsupported properties: spacing",
        ),
        (
            {"id": "root", "component": "Text", "text": "Weather", "title": "Invalid"},
            "unsupported properties: title",
        ),
    ],
)
def test_rejects_component_properties_outside_renderable_contract(component, error):
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(_messages([component]), surface_id="surface-1")


@pytest.mark.parametrize(
    ("components", "error"),
    [
        (
            [
                {
                    "id": "root",
                    "component": "Button",
                    "child": "label",
                    "action": {},
                },
                {"id": "label", "component": "Text", "text": "Run"},
            ],
            "exactly one event",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Button",
                    "child": "label",
                    "action": {"event": "invalid"},
                },
                {"id": "label", "component": "Text", "text": "Run"},
            ],
            "event must be an object",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Button",
                    "child": "label",
                    "action": {"event": {"name": "run", "target": "api"}},
                },
                {"id": "label", "component": "Text", "text": "Run"},
            ],
            "unsupported properties: target",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Button",
                    "child": "label",
                    "action": {"event": {"name": ""}},
                },
                {"id": "label", "component": "Text", "text": "Run"},
            ],
            "event.name must be a string",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Button",
                    "child": "label",
                    "action": {"event": {"name": "run", "context": []}},
                },
                {"id": "label", "component": "Text", "text": "Run"},
            ],
            "event.context must be an object",
        ),
        (
            [{"id": "root", "component": "Row", "children": [1]}],
            "contain component ids",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Column",
                    "children": {"componentId": "item"},
                }
            ],
            "contain component ids",
        ),
        (
            [{"id": "root", "component": "ArtifactCard", "title": 1, "url": "/report"}],
            "ArtifactCard.title must be a string",
        ),
        (
            [{"id": "root", "component": "DataTable", "columns": "bad", "rows": []}],
            "DataTable.columns",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "DataTable",
                    "columns": [{"key": "name", "label": "Name"}],
                    "rows": "bad",
                }
            ],
            "DataTable.rows",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Chart",
                    "chartType": "line",
                    "data": {},
                    "valueKey": "value",
                }
            ],
            "Chart.data",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Form",
                    "fields": [
                        {
                            "name": "name",
                            "label": "Name",
                            "type": "text",
                            "placeholder": "Name",
                        }
                    ],
                    "action": {"event": {"name": "submit"}},
                }
            ],
            "Form field has unsupported properties: placeholder",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Form",
                    "fields": [{"label": "Name", "type": "text"}],
                    "action": {"event": {"name": "submit"}},
                }
            ],
            "require string name and label",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Form",
                    "fields": [
                        {
                            "name": "name",
                            "label": "Name",
                            "type": "text",
                            "required": "yes",
                        }
                    ],
                    "action": {"event": {"name": "submit"}},
                }
            ],
            "required must be boolean",
        ),
        (
            [
                {
                    "id": "root",
                    "component": "Form",
                    "fields": [
                        {
                            "name": "room",
                            "label": "Room",
                            "type": "select",
                            "options": ["suite"],
                        }
                    ],
                    "action": {"event": {"name": "submit"}},
                }
            ],
            "options must contain label/value objects",
        ),
    ],
)
def test_rejects_invalid_component_contract_details(components, error):
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(_messages(components), surface_id="surface-1")


@pytest.mark.parametrize(
    ("raw", "surface_id", "error"),
    [
        ({"invalid": True}, "surface-1", "messages array"),
        ([], "unsafe surface", "Invalid server"),
        (["invalid"], "surface-1", "must be an object"),
        (
            [{"updateComponents": {"components": "invalid"}}],
            "surface-1",
            "must be an array",
        ),
        (
            [{"updateComponents": {"components": ["invalid"]}}],
            "surface-1",
            "must be objects",
        ),
        (
            [
                {
                    "updateComponents": {
                        "components": [{"id": "unsafe id", "component": "Text"}]
                    }
                }
            ],
            "surface-1",
            "safe id",
        ),
        ([{"updateDataModel": "invalid"}], "surface-1", "must be an object"),
        ([{"version": "v1.0", "updateDataModel": {}}], "surface-1", "version"),
        ([{"unsupported": {}}], "surface-1", "wrap components"),
    ],
)
def test_rejects_malformed_message_shapes(raw, surface_id, error):
    with pytest.raises(A2UIValidationError, match=error):
        validate_a2ui_messages(raw, surface_id=surface_id)


def test_rejects_deep_graph_large_action_context_and_large_message():
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

    with pytest.raises(A2UIValidationError, match="Action context"):
        validate_a2ui_messages(
            _messages(
                _components(
                    {
                        "id": "button",
                        "component": "Button",
                        "action": {
                            "event": {
                                "name": "submit",
                                "context": {"value": "x" * (64 * 1024)},
                            }
                        },
                    }
                )
            ),
            surface_id="surface-1",
        )

    with pytest.raises(A2UIValidationError, match="256 KiB"):
        validate_a2ui_messages(
            _messages(
                [{"id": "root", "component": "Text", "text": "x" * (256 * 1024)}]
            ),
            surface_id="surface-1",
        )


def test_rejects_form_fields_that_are_not_an_array():
    with pytest.raises(A2UIValidationError, match="must be an array"):
        validate_a2ui_messages(
            _messages(
                _components({"id": "form", "component": "Form", "fields": "invalid"})
            ),
            surface_id="surface-1",
        )


def test_rejects_components_without_update_components_envelope():
    with pytest.raises(A2UIValidationError, match="wrap components"):
        validate_a2ui_messages(
            {"messages": [{"components": [{"id": "root", "component": "Text"}]}]},
            surface_id="surface-1",
        )
