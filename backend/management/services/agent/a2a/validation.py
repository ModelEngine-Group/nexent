# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


def validate_a2a_agent_name(name: str) -> str:
    """Require a nonempty callable name without whitespace, preserving its value."""
    if not isinstance(name, str) or not name:
        raise ValueError("A2A Agent name must be a non-empty string")
    if any(character.isspace() for character in name):
        raise ValueError("A2A Agent name must not contain spaces or other whitespace")
    return name
