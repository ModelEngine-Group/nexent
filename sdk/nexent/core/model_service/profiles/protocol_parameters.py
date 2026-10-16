# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Fallback request declarations for the registered OpenAI chat protocol."""


def openai_chat_parameter_rules():
    """Declare wire fields without assigning provider capability or request defaults."""
    fields = {
        "temperature": ({"type": ["number", "null"]}, "/temperature", True),
        "top_p": ({"type": ["number", "null"], "minimum": 0, "maximum": 1}, "/top_p", True),
        "max_output_tokens": ({"type": "integer", "minimum": 1}, "/max_tokens", True),
        "stop": ({"type": ["string", "array"], "items": {"type": "string"}}, "/stop", False),
        "response_format": ({"type": "object"}, "/response_format", False),
    }
    return [{"key": key, "schema": schema, "visible": visible, "editable": True, "required": False,
        "allowed_scopes": ["outlet", "conversation"] if visible else ["outlet"],
        "ui_group": "advanced" if visible else "runtime", "owner": "provider",
        "source": {"ref": "openai_chat_protocol_parameters_v2", "version": 2},
        "api_binding": {"path": path, "transform_ref": "identity_v1", "transform_version": 1}}
        for key, (schema, path, visible) in fields.items()]
