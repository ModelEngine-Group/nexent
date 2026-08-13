"""Constants for A2UI protocol."""

A2UI_OPEN_TAG = "<a2ui-json>"
A2UI_CLOSE_TAG = "</a2ui-json>"
A2UI_PROTOCOL_VERSION = "0.9"
A2UI_CLIENT_EVENT_TYPE = "a2ui.client_event"

A2UI_MESSAGE_KEYS = frozenset({
    "beginRendering",
    "surfaceUpdate",
    "dataModelUpdate",
    "deleteSurface",
})