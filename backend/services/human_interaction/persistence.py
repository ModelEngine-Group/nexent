"""Service-owned persistence validation, executed inside the repository's locks."""

import json

from sqlalchemy import BigInteger, Integer, String

from database.db_models import HumanEvent, HumanExecution, HumanRequest, HumanRun

from .models import InteractionError

RUN_STATUSES = {
    "INITIALIZING",
    "READY",
    "RUNNING",
    "WAITING_HUMAN",
    "COMPLETED",
    "FAILED",
    "STOPPED",
    "EXPIRED",
    "RECOVERY_REQUIRED",
}
REQUEST_STATUSES = {"PENDING", "DECIDED", "CANCELLED", "EXPIRED"}
REQUEST_KINDS = {"CLARIFICATION", "ACTION_APPROVAL", "USER_STEERING"}
EXECUTION_STATUSES = {"PREPARED", "STARTED", "SUCCEEDED", "REJECTED", "UNKNOWN"}


def validate_record(row, tx, *, creating):
    """Validate the final write, including scheduler and receipt updates."""
    for column in row.__table__.columns:
        value = getattr(row, column.key)
        if column.primary_key and creating and value is None:
            continue
        if value is None:
            if not column.nullable:
                raise InteractionError(f"{column.key} is required", 422)
            continue
        if (
            isinstance(column.type, String)
            and column.type.length
            and (not isinstance(value, str) or len(value) > column.type.length)
        ):
            raise InteractionError(f"{column.key} exceeds its string boundary", 422)
        if isinstance(column.type, Integer):
            maximum = 2**63 - 1 if isinstance(column.type, BigInteger) else 2**31 - 1
            if type(value) is not int or not 0 <= value <= maximum:
                raise InteractionError(f"{column.key} is outside its integer boundary", 422)
    if row.delete_flag not in {"N", "Y"}:
        raise InteractionError("Invalid soft-delete marker", 422)
    if isinstance(row, HumanRun):
        if row.status not in RUN_STATUSES or row.pause_requested not in {0, 1}:
            raise InteractionError("Invalid run state", 422)
        return
    if row.run_record_id != tx.run.run_record_id or (
        tx.run.delete_flag != "N" and (creating or row.delete_flag != "Y")
    ):
        raise InteractionError("The record must reference the active locked run", 422)
    if isinstance(row, HumanRequest):
        if row.kind not in REQUEST_KINDS or row.status not in REQUEST_STATUSES or row.version < 1:
            raise InteractionError("Invalid human request state", 422)
        others = [item for item in tx.requests() if item is not row]
        if creating and any(item.request_id == row.request_id for item in others):
            raise InteractionError("A request with this public identity already exists")
        if row.status == "PENDING" and row.delete_flag == "N" and any(item.status == "PENDING" for item in others):
            raise InteractionError("This run already has a pending human request")
    elif isinstance(row, HumanExecution):
        if row.status not in EXECUTION_STATUSES:
            raise InteractionError("Invalid execution state", 422)
        if creating and tx.execution(row.slot) is not None:
            raise InteractionError("This run already has an execution at this slot")
    elif isinstance(row, HumanEvent):
        payload = row.payload
        chunk = (
            isinstance(payload, dict) and set(payload) == {"chunk_cipher"} and isinstance(payload["chunk_cipher"], str)
        )
        state = (
            isinstance(payload, dict)
            and set(payload) == {"type", "content"}
            and isinstance(payload["type"], str)
            and bool(payload["type"])
            and isinstance(payload["content"], dict)
        )
        if not (chunk or state):
            raise InteractionError("Invalid replay event envelope", 422)
        try:
            json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise InteractionError("Replay event must contain JSON values", 422) from exc
        if row.seq < 1 or row.seq > tx.run.event_seq:
            raise InteractionError("Invalid replay event sequence", 422)
        if creating and (
            row.seq <= tx.event_floor
            or any(
                isinstance(item, HumanEvent)
                and item is not row
                and item.run_record_id == row.run_record_id
                and item.seq == row.seq
                for item in tx.session.new
            )
        ):
            raise InteractionError("This run already has an event at this sequence")
