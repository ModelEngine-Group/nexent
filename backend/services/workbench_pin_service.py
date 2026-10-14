"""Workbench pin service identity and relationship boundary."""

from consts.exceptions import UnauthorizedError, ValidationError
from database.workbench_pin_db import list_workbench_pins, set_workbench_pin


def _validate_identity(user_id: str, tenant_id: str) -> None:
    if not user_id or not tenant_id:
        raise UnauthorizedError("Please login first")
    if len(user_id) > 100 or len(tenant_id) > 100:
        raise ValidationError("Invalid pin identity")


def get_workbench_pins(user_id: str, tenant_id: str) -> dict:
    _validate_identity(user_id, tenant_id)
    return {"items": list_workbench_pins(user_id, tenant_id)}


def update_workbench_pin(conversation_id: int, pinned: bool, user_id: str, tenant_id: str) -> dict:
    _validate_identity(user_id, tenant_id)
    if type(conversation_id) is not int or not 0 < conversation_id <= 2147483647 or type(pinned) is not bool:
        raise ValidationError("Invalid Workbench pin")
    return {"items": set_workbench_pin(conversation_id, pinned, user_id, tenant_id)}
