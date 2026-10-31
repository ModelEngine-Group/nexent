"""Helpers for working with Pydantic FieldInfo objects."""

from pydantic.fields import FieldInfo


def unwrap_field_info(value):
    """Resolve a value that may be wrapped in a Pydantic FieldInfo.

    Parameters declared with ``Field(...)`` arrive at ``__init__`` as raw
    FieldInfo instances instead of their declared defaults when they are not
    passed explicitly. This helper extracts the concrete value so callers can
    treat the result as plain data.
    """
    if isinstance(value, FieldInfo):
        if value.default_factory is not None:
            return value.default_factory()
        return value.default
    return value
