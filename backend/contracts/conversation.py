# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Internal message provenance and opaque activity pagination cursors."""

import base64
import json
from datetime import datetime, timezone
from enum import Enum


class MessageSource(str, Enum):
    CHAT = "CHAT"
    AUTOMATION = "AUTOMATION"


def conversation_time_as_utc(value: datetime) -> datetime:
    """Interpret naive storage values as UTC and normalize aware instants."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def encode_activity_cursor(activity: datetime, conversation_id: int) -> str:
    value = [conversation_time_as_utc(activity).isoformat(), conversation_id]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_activity_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        if not cursor or len(cursor) > 512:
            raise ValueError
        value = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        activity = datetime.fromisoformat(value[0])
        identity = value[1]
        if activity.tzinfo is None or type(identity) is not int or identity <= 0:
            raise ValueError
        return activity.astimezone(timezone.utc), identity
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError("Invalid conversation activity cursor") from exc
