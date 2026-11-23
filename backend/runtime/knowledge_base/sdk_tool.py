# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Synchronous SDK tool boundary over Runtime-owned standard knowledge retrieval."""

import asyncio
from time import monotonic
from uuid import uuid4

from contracts.errors.exceptions import RuntimeUpstreamError
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.storage.errors import Conflict, NotFound, ScopeDenied
from nexent.storage.models import OperationContext


class RuntimeKnowledgeTool:
    def __init__(self, search, *, rerank_model=None):
        self.search, self.rerank_model = search, rerank_model

    def __call__(self, *, query, index_names, search_mode, top_k, cancellation_scope=None):
        async def execute():
            loop, task = asyncio.get_running_loop(), asyncio.current_task()
            token = None
            if cancellation_scope is not None:
                if cancellation_scope.cancelled:
                    raise RunTerminated()
                token = cancellation_scope.register_closer(lambda: loop.call_soon_threadsafe(task.cancel))
            try:
                context = OperationContext("sdk-knowledge-" + uuid4().hex, monotonic() + 180)
                rows = await self.search.search(query, index_names, search_mode=search_mode, top_k=top_k,
                                               rerank_model=self.rerank_model,
                                               context=context)
                results = []
                for hit in rows:
                    legacy = None
                    if hit.legacy_image is not None:
                        try:
                            legacy = await self.search.pin_legacy_image(hit.legacy_image, context=context)
                        except (Conflict, NotFound, ScopeDenied):
                            continue
                        except RuntimeUpstreamError as error:
                            if error.status_code not in {403, 404, 409}:
                                raise
                            continue
                    results.append(self._row(hit, legacy))
                if cancellation_scope is not None and cancellation_scope.cancelled:
                    raise RunTerminated()
                return {"results": results, "total": len(results)}
            except asyncio.CancelledError:
                if cancellation_scope is not None and cancellation_scope.cancelled:
                    raise RunTerminated() from None
                raise
            finally:
                if token is not None:
                    cancellation_scope.unregister_closer(token)
        return asyncio.run(execute())

    @staticmethod
    def _row(hit, legacy=None):
        document = hit.public_document or {}
        return {
            "content": hit.content, "filename": hit.filename, "source_type": "file",
            "path_or_url": document.get("path_or_url", ""),
            "score": hit.score, "score_details": {**hit.score_details, "score_kind": hit.score_kind},
            "location": hit.location,
            **({"file_ref": hit.model_dump(include={"knowledge_id", "file_id", "file_version"})}
               if hit.file_id is not None else {}),
            **({"legacy_image_ref": legacy.model_dump()} if legacy is not None else {}),
            **({"image_ref": hit.image_ref.model_dump()} if hit.image_ref is not None else {}),
        }
