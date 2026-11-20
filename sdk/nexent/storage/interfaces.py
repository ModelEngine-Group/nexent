# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""In-process storage ports. Concrete drivers belong to Infrastructure."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from .models import (
    TTL,
    ByteRange,
    CapabilitySet,
    Comparison,
    DeleteReceipt,
    FieldPatch,
    Junction,
    KVEntry,
    Missing,
    ObjectInventoryEntry,
    ObjectMetadata,
    ObjectRef,
    OperationContext,
    Page,
    PageRequest,
    ReadConsistency,
    Record,
    RecordKey,
    RecordQuery,
    Revision,
    SearchHit,
    SearchQuery,
    StorageScope,
    VectorCollectionInfo,
    VectorCollectionStatistics,
    VectorGroup,
    VectorGroupQuery,
    VectorKey,
    VectorRecord,
    VectorSummaryField,
    WriteReceipt,
)
from .queue import WorkQueue


class StoragePort(Protocol):
    @property
    def scope(self) -> StorageScope: ...

    @property
    def capabilities(self) -> CapabilitySet: ...

    def close(self) -> None: ...


class CollectionInventory(StoragePort, Protocol):
    def count(self, *, context: OperationContext) -> int:
        """Count visible collections in a trusted binding, without exposing names."""
        ...


class KeyValueStore(StoragePort, Protocol):
    def get(self, key: str, *, context: OperationContext) -> KVEntry | None: ...

    def get_many(self, keys: tuple[str, ...], *, context: OperationContext) -> tuple[KVEntry | None, ...]: ...

    def put(self, key: str, value: bytes, *, ttl: TTL, context: OperationContext) -> WriteReceipt: ...

    def compare_exchange(
        self, key: str, expected: Revision | Missing, value: bytes, *, ttl: TTL, context: OperationContext
    ) -> WriteReceipt: ...

    def delete(self, key: str, *, expected: Revision | None = None, context: OperationContext) -> WriteReceipt: ...

    def increment(self, key: str, delta: int, *, ttl: TTL, context: OperationContext) -> KVEntry: ...

    def scan(self, prefix: str, page: PageRequest, *, context: OperationContext) -> Page[str]: ...


class AsyncKeyValueStore(Protocol):
    @property
    def scope(self) -> StorageScope: ...

    @property
    def capabilities(self) -> CapabilitySet: ...

    async def get(self, key: str, *, context: OperationContext) -> KVEntry | None: ...

    async def put(self, key: str, value: bytes, *, ttl: TTL, context: OperationContext) -> WriteReceipt: ...

    async def compare_exchange(
        self, key: str, expected: Revision | Missing, value: bytes, *, ttl: TTL, context: OperationContext
    ) -> WriteReceipt: ...

    async def delete(
        self, key: str, *, expected: Revision | None = None, context: OperationContext
    ) -> WriteReceipt: ...


class RecordStore(StoragePort, Protocol):
    def get(
        self,
        dataset: str,
        key: RecordKey,
        *,
        fields: tuple[str, ...] = (),
        consistency: ReadConsistency = ReadConsistency.AUTHORITATIVE,
        context: OperationContext,
    ) -> Record | None: ...

    def query(
        self, dataset: str, query: RecordQuery, page: PageRequest, *, context: OperationContext
    ) -> Page[Record]: ...

    def create(self, dataset: str, values: Record, *, context: OperationContext) -> Record: ...

    def patch(
        self,
        dataset: str,
        key: RecordKey,
        patch: FieldPatch,
        *,
        expected: Revision | None = None,
        context: OperationContext,
    ) -> WriteReceipt: ...

    def delete(
        self, dataset: str, key: RecordKey, *, expected: Revision | None = None, context: OperationContext
    ) -> DeleteReceipt: ...

    def count(self, dataset: str, query: RecordQuery, *, context: OperationContext) -> int: ...

    def sum(self, dataset: str, field: str, query: RecordQuery, *, context: OperationContext) -> int | float:
        """Sum a catalog numeric field within scope; an empty set returns zero."""
        ...

    def sum_by(
        self, dataset: str, field: str, group_by: str, query: RecordQuery, *, context: OperationContext
    ) -> dict[RecordKey, int | float]:
        """Return scoped numeric totals by a catalog string or integer field."""
        ...

    def transaction(self, *, context: OperationContext) -> AbstractContextManager["RecordStore"]: ...

    def claim(
        self, dataset: str, query: RecordQuery, patch: FieldPatch, *, limit: int = 1, context: OperationContext
    ) -> tuple[Record, ...]:
        """Claim a bounded candidate set inside a transaction; require skip-locked capability."""
        ...


class ObjectInventory(StoragePort, Protocol):
    def first_page(self, prefix: str, *, limit: int, context: OperationContext) -> tuple[ObjectInventoryEntry, ...]:
        """Read one bounded page from an explicitly configured inventory."""
        ...


class ObjectStore(StoragePort, Protocol):
    def put(
        self, ref: ObjectRef, stream: BinaryIO, *, content_type: str, size: int, context: OperationContext
    ) -> ObjectMetadata: ...

    def stat(self, ref: ObjectRef, *, context: OperationContext) -> ObjectMetadata: ...

    def open_read(
        self,
        ref: ObjectRef,
        *,
        byte_range: ByteRange | None = None,
        expected: Revision | None = None,
        context: OperationContext,
    ) -> AbstractContextManager[BinaryIO]: ...

    def list(self, prefix: str, page: PageRequest, *, context: OperationContext) -> Page[ObjectMetadata]: ...

    def copy(self, source: ObjectRef, target: ObjectRef, *, context: OperationContext) -> ObjectMetadata: ...

    def delete(
        self, ref: ObjectRef, *, expected: Revision | None = None, context: OperationContext
    ) -> DeleteReceipt: ...


class VectorStore(StoragePort, Protocol):
    def group(self, collection: str, query: VectorGroupQuery, *, where: Comparison | Junction | None = None,
              context: OperationContext) -> tuple[VectorGroup, ...]:
        """Read bounded groups ordered by descending count and ascending scalar key."""
        ...

    def collection_exists(self, collection: str, *, context: OperationContext) -> bool: ...

    def delete_empty_collection(self, collection: str, *, context: OperationContext) -> DeleteReceipt: ...

    def ensure_collection(self, collection: str, *, context: OperationContext) -> VectorCollectionInfo: ...

    def describe_collection(self, collection: str, *, context: OperationContext) -> VectorCollectionInfo: ...

    def statistics(self, collection: str, fields: tuple[VectorSummaryField, ...] = (),
                   *, context: OperationContext) -> VectorCollectionStatistics:
        """Read physical collection metrics and bounded scalar payload summaries."""
        ...

    def upsert(self, records: tuple[VectorRecord, ...], *, context: OperationContext) -> tuple[WriteReceipt, ...]: ...

    def put(self, record: VectorRecord, *, expected_generation: Revision | None,
            context: OperationContext) -> WriteReceipt: ...

    def get(self, key: VectorKey, *, context: OperationContext, include_vector: bool = True) -> VectorRecord | None: ...

    def delete_key(self, key: VectorKey, *, expected_generation: Revision | None,
                   context: OperationContext) -> DeleteReceipt: ...

    def patch_payload(
        self, key: VectorKey, patch: FieldPatch, *, expected_generation: Revision | None,
        context: OperationContext,
    ) -> WriteReceipt:
        """Edit explicitly mutable payload fields without changing vectors or identity."""
        ...

    def search(self, collection: str, query: SearchQuery, *, context: OperationContext) -> tuple[SearchHit, ...]: ...

    def scan(
        self, collection: str, where: Comparison | Junction | None, page: PageRequest,
        *, context: OperationContext, include_vector: bool = True, allow_missing_vector: bool = False,
    ) -> Page[VectorRecord]:
        """Read scoped keys; explicitly optional vectors distinguish absence from invalid data."""
        ...

    def delete(
        self, collection: str, where: Comparison | Junction, *, context: OperationContext
    ) -> tuple[DeleteReceipt, ...]: ...

    def count(self, collection: str, where: Comparison | Junction | None, *, context: OperationContext) -> int: ...


@dataclass(frozen=True)
class StorageInterface:
    """Composition supplies only explicitly authorized, capability-checked ports."""

    kv: KeyValueStore | None = None
    records: RecordStore | None = None
    objects: ObjectStore | None = None
    vectors: VectorStore | None = None
    queue: WorkQueue | None = None
    collections: CollectionInventory | None = None
