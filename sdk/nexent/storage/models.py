# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral values shared by storage consumers and Infrastructure adapters."""

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from time import monotonic
from typing import Generic, Protocol, TypeAlias, TypeVar

from .errors import CapabilityUnsupported, DeadlineExceeded, InvalidInput, OperationCancelled


JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
Record: TypeAlias = dict[str, JSONValue]
RecordKey: TypeAlias = str | int
T = TypeVar("T")


def _nonempty(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class StorageScope:
    """Only trusted composition and authorization layers issue scoped handles."""

    service_role: str
    tenant_id: str | None
    actor_id: str
    namespaces: frozenset[str]
    system: bool = False
    resource_prefix: str = ""

    def __post_init__(self):
        if not isinstance(self.namespaces, (set, frozenset, tuple, list)):
            raise InvalidInput()
        object.__setattr__(self, "namespaces", frozenset(self.namespaces))
        if not _nonempty(self.service_role) or not _nonempty(self.actor_id):
            raise InvalidInput()
        if type(self.system) is not bool or not isinstance(self.resource_prefix, str):
            raise InvalidInput()
        if self.system and self.tenant_id is not None:
            raise InvalidInput()
        if not self.system and not _nonempty(self.tenant_id):
            raise InvalidInput()
        if not self.namespaces or not all(_nonempty(name) for name in self.namespaces):
            raise InvalidInput()


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class OperationContext:
    operation_id: str
    deadline: float
    cancelled: Cancellation | None = field(default=None, repr=False, compare=False)
    trace_id: str | None = None

    def __post_init__(self):
        if (
            not _nonempty(self.operation_id)
            or not isinstance(self.deadline, (int, float))
            or isinstance(self.deadline, bool)
            or not isfinite(self.deadline)
        ):
            raise InvalidInput()

    def remaining(self) -> float:
        if self.cancelled is not None and self.cancelled.is_set():
            raise OperationCancelled(operation_id=self.operation_id)
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise DeadlineExceeded(operation_id=self.operation_id)
        return remaining


@dataclass(frozen=True)
class CapabilitySet:
    """Capabilities are explicit contracts, including operation granularity."""

    supported: frozenset[str] = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "supported", frozenset(self.supported))

    def require(self, *required: str) -> None:
        if not set(required) <= self.supported:
            raise CapabilityUnsupported()


@dataclass(frozen=True)
class Revision:
    value: str

    def __post_init__(self):
        if not _nonempty(self.value) or len(self.value) > 256:
            raise InvalidInput()


class Missing(Enum):
    VALUE = "missing"


class TTLMode(str, Enum):
    DURATION = "duration"
    PRESERVE = "preserve"
    NO_EXPIRY = "no-expiry"


@dataclass(frozen=True)
class TTL:
    mode: TTLMode
    seconds: float | None = None

    def __post_init__(self):
        if not isinstance(self.mode, TTLMode):
            raise InvalidInput()
        if self.mode is TTLMode.DURATION:
            if (
                not isinstance(self.seconds, (int, float))
                or isinstance(self.seconds, bool)
                or not isfinite(self.seconds)
                or self.seconds <= 0
            ):
                raise InvalidInput()
        elif self.seconds is not None:
            raise InvalidInput()


@dataclass(frozen=True)
class KVEntry:
    value: bytes
    revision: Revision


class WriteOutcome(str, Enum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WriteReceipt:
    operation_id: str
    matched: bool
    revision: Revision | None = None
    outcome: WriteOutcome = WriteOutcome.CONFIRMED


@dataclass(frozen=True)
class DeleteReceipt:
    operation_id: str
    deleted: bool


@dataclass(frozen=True)
class PageRequest:
    limit: int = 100
    cursor: str | None = None

    def __post_init__(self):
        if type(self.limit) is not int or not 1 <= self.limit <= 1000:
            raise InvalidInput()


@dataclass(frozen=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class Comparison:
    field: str
    operator: str
    value: JSONValue = None


@dataclass(frozen=True)
class Junction:
    operator: str
    terms: tuple["Comparison | Junction", ...]

    def __post_init__(self):
        object.__setattr__(self, "terms", tuple(self.terms))


@dataclass(frozen=True)
class Sort:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class RecordQuery:
    fields: tuple[str, ...] = ()
    where: Comparison | Junction | None = None
    order_by: tuple[Sort, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "order_by", tuple(self.order_by))


class ReadConsistency(str, Enum):
    AUTHORITATIVE = "authoritative"
    CACHED_ALLOWED = "cached-allowed"


@dataclass(frozen=True)
class FieldPatch:
    set_values: Record = field(default_factory=dict)
    unset_fields: tuple[str, ...] = ()
    increments: dict[str, int | float] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectRef:
    space: str
    key: str
    version: Revision | None = None


@dataclass(frozen=True)
class ObjectMetadata:
    ref: ObjectRef
    size: int
    content_type: str
    etag: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int | None = None

    def __post_init__(self):
        if type(self.start) is not int or self.start < 0:
            raise InvalidInput()
        if self.end is not None and (type(self.end) is not int or self.end <= self.start):
            raise InvalidInput()


@dataclass(frozen=True)
class VectorKey:
    collection: str
    key: str


@dataclass(frozen=True)
class VectorRecord:
    key: VectorKey
    vector: tuple[float, ...]
    payload: Record
    generation: Revision | None = None


@dataclass(frozen=True)
class SearchQuery:
    vector: tuple[float, ...] | None = None
    text: str | None = None
    mode: str = "dense"
    where: Comparison | Junction | None = None
    limit: int = 10
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    key: VectorKey
    score: float
    score_kind: str
    payload: Record
    generation: Revision | None = None


@dataclass(frozen=True)
class LogEvent:
    event_id: str
    cursor: str
    value: bytes


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    handler: str
    arguments: Record
    revision: Revision | None = None
