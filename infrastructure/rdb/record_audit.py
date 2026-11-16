# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit audit-column mappings and neutral UTC timestamp values."""

from dataclasses import dataclass
from datetime import datetime, timezone

from nexent.storage.errors import InvalidInput


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        raise InvalidInput() from None
    if result.tzinfo is None:
        raise InvalidInput()
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class RecordAudit:
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str
    inactive_value: str = "Y"

    @property
    def fields(self):
        return frozenset(
            {self.created_at, self.updated_at, self.created_by, self.updated_by}
        )

    @property
    def dates(self):
        return frozenset({self.created_at, self.updated_at})

    def values(self, actor, *, create=False):
        now = datetime.now(timezone.utc)
        values = {self.updated_at: now, self.updated_by: actor}
        if create:
            values.update({self.created_at: now, self.created_by: actor})
        return values

    def neutral(self, row):
        result = dict(row)
        for name in self.dates & result.keys():
            value = result[name]
            if value is not None:
                if not isinstance(value, datetime):
                    raise InvalidInput()
                result[name] = (
                    value.replace(tzinfo=value.tzinfo or timezone.utc)
                    .astimezone(timezone.utc)
                    .isoformat()
                )
        return result
