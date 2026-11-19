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
    VectorKey,
    VectorRecord,
    WriteReceipt,
)


class StoragePort(Protocol):
    @property
    def scope(self) -> StorageScope: ...

    @property
    def capabilities(self) -> CapabilitySet: ...

    def close(self) -> None: ...


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

    def transaction(self, *, context: OperationContext) -> AbstractContextManager["RecordStore"]: ...


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
    def upsert(self, records: tuple[VectorRecord, ...], *, context: OperationContext) -> tuple[WriteReceipt, ...]: ...

    def get(self, key: VectorKey, *, context: OperationContext) -> VectorRecord | None: ...

    def search(self, collection: str, query: SearchQuery, *, context: OperationContext) -> tuple[SearchHit, ...]: ...

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
