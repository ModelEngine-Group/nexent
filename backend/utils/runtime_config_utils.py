"""Copy runtime configuration containers without cloning live service handles."""

from copy import copy
from dataclasses import fields, is_dataclass
from typing import Any

from pydantic import BaseModel


def clone_runtime_config(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """Isolate mutable config data; opaque clients, locks and callbacks stay request-local references."""
    memo = {} if memo is None else memo
    if id(value) in memo:
        return memo[id(value)]
    if isinstance(value, BaseModel):
        result = value.model_copy()
        memo[id(value)] = result
        for name, item in value.__dict__.items():
            object.__setattr__(result, name, clone_runtime_config(item, memo))
        return result
    if isinstance(value, dict):
        result = {}
        memo[id(value)] = result
        result.update((key, clone_runtime_config(item, memo)) for key, item in value.items())
        return result
    if isinstance(value, list):
        result = []
        memo[id(value)] = result
        result.extend(clone_runtime_config(item, memo) for item in value)
        return result
    if isinstance(value, tuple):
        return tuple(clone_runtime_config(item, memo) for item in value)
    if isinstance(value, set):
        return {clone_runtime_config(item, memo) for item in value}
    if is_dataclass(value) and not isinstance(value, type):
        result = copy(value)
        memo[id(value)] = result
        for field in fields(value):
            object.__setattr__(result, field.name, clone_runtime_config(getattr(value, field.name), memo))
        return result
    return value
