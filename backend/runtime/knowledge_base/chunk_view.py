# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read confirmed mutable chunks while retaining original publication and orphan checks."""

from dataclasses import dataclass

from contracts.agentos_knowledge import KnowledgeChunk, ModelVersion
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_chunk_mutation import CHANGES
from contracts.knowledge_chunk_projection import public_chunk_value
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery, Sort
from runtime.knowledge_base.chunk_journal import ChunkMutationJournal

from infrastructure.agent_model_config import normalize_model_revision


def validate_read_ports(records, vectors, grant, actor):
    if (set(records) != {r.knowledge_id for r in grant.knowledge_bases}
        or set(vectors) != {r.collection for r in grant.knowledge_bases}):
        raise ScopeDenied()
    for resource in grant.knowledge_bases:
        if resource.resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
            raise ScopeDenied()
        for port in (records[resource.knowledge_id], vectors[resource.collection]):
            scope = port.scope
            if (scope.system or scope.resource_prefix or scope.service_role != "runtime"
                or scope.actor_id != actor.user_id or scope.tenant_id != resource.resource_tenant_id):
                raise ScopeDenied()
        if vectors[resource.collection].scope.namespaces != {resource.collection}:
            raise ScopeDenied()


@dataclass
class _State:
    original: bool
    original_index: int | None
    alive: bool
    latest: dict
    creation: str | None = None


class _History:
    def __init__(self, rows, *, standalone):
        self.states, self.delta, self.structural = {}, 0, False
        for row in rows:
            key, operation, delta = (
                row["chunk_id"],
                row["operation"],
                row["count_delta"],
            )
            if (
                operation not in {"create", "update", "delete"}
                or type(delta) is not int
            ):
                raise Conflict()
            state = self.states.get(key)
            if state is None:
                original = (
                    operation == "update"
                    or operation == "create"
                    and delta == 0
                    or operation == "delete"
                    and delta == -1
                )
                if original and standalone:
                    raise Conflict()
                state = _State(
                    original, row["chunk_index"] if original else None, original, row
                )
                self.states[key] = state
            expected = (
                (0 if state.alive else 1)
                if operation == "create"
                else (-1 if state.alive else 0)
                if operation == "delete"
                else 0
            )
            if delta != expected or operation == "update" and not state.alive:
                raise Conflict()
            if operation == "create":
                state.alive, state.creation = True, row["mutation_id"]
            elif operation == "delete":
                state.alive, state.creation = False, None
            state.latest = row
            self.delta += delta
            self.structural = self.structural or operation != "update"


class ChunkReadView:
    def __init__(self, records, knowledge_id, *, context):
        self.records, self.knowledge_id = records, knowledge_id
        self.journal = ChunkMutationJournal(records, knowledge_id)
        self.version = self.journal.revision(context=context)
        self.histories = {}

    def stable(self, *, context):
        if self.journal.revision(context=context) != self.version:
            raise Conflict()

    def _history(self, manifest=None, *, context):
        self.stable(context=context)
        key = (
            None
            if manifest is None
            else (
                manifest["file_id"],
                manifest["visible_version"],
                manifest["visible_generation"],
            )
        )
        if key not in self.histories:
            terms = [
                Comparison("knowledge_id", "eq", self.knowledge_id),
                Comparison("status", "eq", "completed"),
                Comparison("native_documents", "eq", False),
            ]
            terms += (
                [Comparison("file_id", "is_null", True)]
                if key is None
                else [
                    Comparison("file_id", "eq", key[0]),
                    Comparison("file_version", "eq", key[1]),
                    Comparison("generation", "eq", key[2]),
                ]
            )
            rows, cursor, seen, epoch = [], None, set(), 0
            while True:
                page = self.records.query(
                    CHANGES,
                    RecordQuery(
                        where=Junction("and", tuple(terms)),
                        order_by=(Sort("commit_epoch"),),
                    ),
                    PageRequest(limit=500, cursor=cursor),
                    context=context,
                )
                for row in page.items:
                    if (
                        row["tenant_id"] != self.records.scope.tenant_id
                        or row["knowledge_id"] != self.knowledge_id
                    ):
                        raise ScopeDenied()
                    if (
                        row["status"] != "completed"
                        or type(row["commit_epoch"]) is not int
                        or not epoch < row["commit_epoch"] <= self.version
                    ):
                        raise Conflict()
                    if key is None and any(
                        row[name] is not None
                        for name in (
                            "file_id",
                            "file_version",
                            "generation",
                            "chunk_index",
                        )
                    ):
                        raise ScopeDenied()
                    if (
                        key is not None
                        and (row["file_id"], row["file_version"], row["generation"])
                        != key
                    ):
                        raise ScopeDenied()
                    epoch = row["commit_epoch"]
                    rows.append(row)
                if page.next_cursor is None:
                    break
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
            self.histories[key] = _History(rows, standalone=key is None)
        self.stable(context=context)
        return self.histories[key]

    def file_count(self, manifest, job, *, context):
        history = self._history(manifest, context=context)
        base = job["chunk_count"]
        if type(base) is not int or base < 0 or base + history.delta < 0:
            raise Conflict()
        original = {}
        for key, state in history.states.items():
            if state.original:
                index = state.original_index
                if type(index) is not int or not 0 <= index < base or index in original:
                    raise Conflict()
                original[index] = key
        return base + history.delta

    def standalone_count(self, *, context):
        history = self._history(context=context)
        if history.delta < 0 or history.delta != sum(
            state.alive for state in history.states.values()
        ):
            raise Conflict()
        return history.delta

    def allows_candidate(self, record, *, context):
        """Apply confirmed per-key changes after the caller checks current file visibility."""
        data = record.payload
        if data.get("knowledge_id") != self.knowledge_id:
            raise ScopeDenied()
        if record.generation is None:
            return False
        if data.get("file_id") is None:
            if any(data.get(name) is not None for name in ("file_version", "chunk_index")):
                raise ScopeDenied()
            history = self._history(context=context)
            state = history.states.get(record.key.key)
            return bool(state and state.alive and state.creation == record.generation.value)
        history = self._history({"file_id": data["file_id"], "visible_version": data["file_version"],
                                 "visible_generation": record.generation.value}, context=context)
        state = history.states.get(record.key.key)
        return state is None or state.alive and state.latest["chunk_index"] == data.get("chunk_index")

    def _mutation_state(self, record, *, context):
        data = record.payload
        if data.get("knowledge_id") != self.knowledge_id:
            raise ScopeDenied()
        if record.generation is None:
            return None
        manifest = None if data.get("file_id") is None else {
            "file_id": data["file_id"], "visible_version": data["file_version"],
            "visible_generation": record.generation.value}
        return self._history(manifest, context=context).states.get(record.key.key)

    def has_manual_create(self, record, *, context):
        state = self._mutation_state(record, context=context)
        return bool(state and state.alive and state.creation)

    def has_confirmed_mutation(self, record, *, context):
        return self._mutation_state(record, context=context) is not None

    @staticmethod
    def _scan(vectors, resource, where, *, context, include_vectors=False, vectors_only=False):
        cursor, seen = None, set()
        while True:
            context.remaining()
            page = vectors.scan(
                resource.collection,
                where,
                PageRequest(limit=500, cursor=cursor),
                context=context,
                include_vector=include_vectors,
                **({"allow_missing_vector": True} if include_vectors else {}),
                **({"vectors_only": True} if vectors_only else {}),
            )
            yield from page.items
            if page.next_cursor is None:
                break
            if page.next_cursor in seen:
                raise Conflict()
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    @staticmethod
    def _model(record, model):
        if record.payload.get(
            "embedding_model_id"
        ) != model.model_id or normalize_model_revision(
            record.payload.get("embedding_revision")
        ) != normalize_model_revision(model.revision):
            raise Conflict()

    def _dto(self, record, resource):
        data = record.payload
        if (
            record.key.collection != resource.collection
            or data.get("knowledge_id") != self.knowledge_id
        ):
            raise ScopeDenied()
        return KnowledgeChunk(
            knowledge_id=self.knowledge_id,
            chunk_id=record.key.key,
            file_id=data.get("file_id"),
            file_version=data.get("file_version"),
            chunk_index=data.get("chunk_index"),
            content=data["content"],
            filename=public_chunk_value(data.get("location", {}), "filename", data.get("filename", "")),
            location=data.get("location", {}),
        )

    def file_window(self, vectors, resource, manifest, job, start, end, *, context):
        return [self._dto(row, resource) for row in self.file_records(
            vectors, resource, manifest, job, start, end, context=context)]

    def file_records(self, vectors, resource, manifest, job, start, end, *, context, include_vectors=False):
        count = self.file_count(manifest, job, context=context)
        if not 0 <= start <= end <= count:
            raise InvalidInput()
        history = self._history(manifest, context=context)
        reference = {
            "knowledge_id": self.knowledge_id,
            "file_id": manifest["file_id"],
            "file_version": manifest["visible_version"],
        }
        terms = [Comparison(name, "eq", value) for name, value in reference.items()]
        if not history.structural:
            terms += [
                Comparison("chunk_index", "gte", start),
                Comparison("chunk_index", "lt", end),
            ]
        where = Junction("and", tuple(terms))
        model = ModelVersion.model_validate(job["request_payload"]["embedding_model"])
        selected, keys, original = (
            [],
            set(),
            {
                state.original_index: key
                for key, state in history.states.items()
                if state.original
            },
        )
        for record in self._scan(vectors, resource, where, context=context, include_vectors=include_vectors):
            data = record.payload
            if record.key.collection != resource.collection or any(
                data.get(name) != value for name, value in reference.items()
            ):
                raise ScopeDenied()
            if (
                record.generation is None
                or record.generation.value != manifest["visible_generation"]
            ):
                continue
            index, key = data.get("chunk_index"), record.key.key
            if type(index) is not int or index < 0 or key in keys:
                raise Conflict()
            keys.add(key)
            state = history.states.get(key)
            if state is not None and (
                not state.alive or state.latest["chunk_index"] != index
            ):
                raise Conflict()
            if not history.structural:
                if not start <= index < end or any(
                    row.payload["chunk_index"] == index for row in selected
                ):
                    raise Conflict()
            elif state is None:
                if (
                    index >= job["chunk_count"]
                    or index in original
                    and original[index] != key
                ):
                    raise Conflict()
                original[index] = key
            if state is None or state.creation is None:
                self._model(record, model)
            self._dto(record, resource)
            selected.append(record)
        if history.structural:
            if (
                len(selected) != count
                or len(original) != job["chunk_count"]
                or any(
                    state.alive and key not in keys
                    for key, state in history.states.items()
                )
            ):
                raise Conflict()
        elif len(selected) != end - start or any(
            state.alive
            and start <= state.latest["chunk_index"] < end
            and key not in keys
            for key, state in history.states.items()
        ):
            raise Conflict()
        selected.sort(key=lambda row: (row.payload["chunk_index"], row.key.key))
        self.stable(context=context)
        return selected[start:end] if history.structural else selected

    def standalone_window(self, vectors, resource, start, end, *, context):
        return [self._dto(row, resource) for row in self.standalone_records(vectors, resource, start, end, context=context)]

    def standalone_records(self, vectors, resource, start, end, *, context, include_vectors=False):
        count = self.standalone_count(context=context)
        if not 0 <= start <= end <= count:
            raise InvalidInput()
        history = self._history(context=context)
        selected, keys = [], set()
        where = Junction(
            "and",
            (
                Comparison("knowledge_id", "eq", self.knowledge_id),
                Comparison("file_id", "is_null", True),
            ),
        )
        for record in self._scan(vectors, resource, where, context=context, include_vectors=include_vectors):
            data, key = record.payload, record.key.key
            if any(
                data.get(name) is not None
                for name in ("file_id", "file_version", "chunk_index")
            ):
                raise ScopeDenied()
            state = history.states.get(key)
            if (
                key in keys
                or state is None
                or not state.alive
                or record.generation is None
                or record.generation.value != state.creation
            ):
                raise Conflict()
            keys.add(key)
            self._dto(record, resource)
            selected.append(record)
        if len(selected) != count:
            raise Conflict()
        selected.sort(key=lambda row: row.key.key)
        self.stable(context=context)
        return selected[start:end]
