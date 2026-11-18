# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Admit chunk writes only against current published files and an open KB."""

from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from runtime.knowledge_base.chunk_journal import (
    ChunkMutationJournal,
    assert_knowledge_open,
)
from runtime.knowledge_base.jobs import lock_file_manifest
from runtime.knowledge_base.publication import published_job


class ChunkMutationAdmission(ChunkMutationJournal):
    def reserve(self, intent, *, context):
        if not isinstance(intent, ChunkMutationIntent):
            raise InvalidInput()
        intent = ChunkMutationIntent.model_validate(intent.model_dump(mode="json"))
        if intent.knowledge_id != self.knowledge_id:
            raise ScopeDenied()
        with self.records.transaction(context=context) as tx:
            self._locked_state(tx, context)
            self._validate_target(tx, intent, context)
            return self._reserve(tx, intent, context)

    def _validate_target(self, tx, intent, context):
        assert_knowledge_open(tx, self.knowledge_id, context=context)
        if intent.file_ref is not None:
            manifest = lock_file_manifest(tx, intent.file_ref, context)
            if (
                manifest["visible_version"] != intent.file_ref.file_version
                or manifest["visible_generation"] != intent.generation
                or manifest["tombstone_version"] >= intent.file_ref.file_version
            ):
                raise Conflict()
            published_job(tx, intent, manifest, context=context)

    def revalidate(self, intent, *, context):
        if not isinstance(intent, ChunkMutationIntent):
            raise InvalidInput()
        intent = ChunkMutationIntent.model_validate(intent.model_dump(mode="json"))
        if intent.knowledge_id != self.knowledge_id:
            raise ScopeDenied()
        with self.records.transaction(context=context) as tx:
            self._locked_state(tx, context)
            self._validate_target(tx, intent, context)
