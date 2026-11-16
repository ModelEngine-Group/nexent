# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run-owned synchronous tool adapter for the reverse AgentOS FileCleanse API."""

import asyncio
import hashlib
import io
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import (
    CleanseArtifact,
    FileCleanseLookup,
    FileCleanseRequest,
    ObjectReference,
)
from contracts.constants.constants import (
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
)
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from nexent.storage.errors import DeadlineExceeded, InvalidInput, OperationCancelled
from nexent.storage.models import ObjectRef, OperationContext, Revision
from nexent.storage.objects import read_verified_object
from runtime.knowledge_base.chunking import chunk_text

from infrastructure.file_processing.text_objects import (
    bind_text_artifact,
    bind_text_stage,
)

logger = logging.getLogger(__name__)


class RunTextCleanser:
    def __init__(
        self,
        actor,
        run_id,
        client,
        *,
        max_bytes,
        seconds=300,
        stage=bind_text_stage,
        artifacts=bind_text_artifact,
    ):
        FileCleanseLookup(run_id=run_id, job_id="0" * 32)
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or type(seconds) not in {int, float}
            or not 0 < seconds <= 300
        ):
            raise InvalidInput()
        self.actor, self.run_id, self.client = actor, run_id, client
        self.max_bytes, self.seconds = max_bytes, seconds
        self.stage, self.artifacts = stage, artifacts

    def _network(self, operation, scope, context):
        async def execute():
            task = asyncio.current_task()
            loop = asyncio.get_running_loop()
            token = (
                scope.register_closer(lambda: loop.call_soon_threadsafe(task.cancel))
                if scope is not None
                else None
            )
            try:
                async with asyncio.timeout(context.remaining()):
                    return await operation()
            finally:
                if token is not None:
                    scope.unregister_closer(token)

        try:
            return asyncio.run(execute())
        except RuntimeServiceTimeoutError as error:
            # The AgentOS transport already logged this request deadline.
            raise DeadlineExceeded(operation_id=context.operation_id) from error
        except RuntimeUpstreamError as error:
            if error.status_code == 504:
                raise DeadlineExceeded(operation_id=context.operation_id) from error
            raise
        except asyncio.CancelledError as error:
            raise OperationCancelled(operation_id=context.operation_id) from error
        except TimeoutError as error:
            logger.warning(
                "run_file_cleanse_timeout operation_id=%s phase=wait threshold_seconds=%s exception_type=%s",
                context.operation_id,
                self.seconds,
                type(error).__name__,
            )
            raise DeadlineExceeded(operation_id=context.operation_id) from error

    async def _wait(self, request, states, context):
        state = await self.client.submit_file_cleanse(
            request, self.actor.user_id, self.actor.tenant_id
        )
        while True:
            if (
                state.run_id != self.run_id
                or states
                and state.job_id != states[0].job_id
            ):
                raise InvalidInput()
            states[:] = [state]
            context.remaining()
            if state.status == "completed":
                return state
            if state.status not in {"queued", "running"}:
                raise InvalidInput()
            await asyncio.sleep(min(0.2, context.remaining()))
            state = await self.client.inspect_file_cleanse(
                FileCleanseLookup(run_id=self.run_id, job_id=state.job_id),
                self.actor.user_id,
                self.actor.tenant_id,
            )

    def __call__(self, filename, content, *, cancellation_scope=None):
        if not isinstance(content, bytes) or not 0 < len(content) <= self.max_bytes:
            raise InvalidInput()
        # Storage adapters must run in the existing synchronous managed tool worker.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise InvalidInput()
        nonce = uuid4().hex
        context = OperationContext(
            "text-cleanse-" + nonce,
            monotonic() + self.seconds,
            cancelled=cancellation_scope.stop_event
            if cancellation_scope is not None
            else None,
        )
        context.remaining()
        objects, ref = self.stage(self.actor, self.run_id, nonce, filename)
        states = []
        try:
            metadata = objects.put(
                ref,
                io.BytesIO(content),
                content_type="application/octet-stream",
                size=len(content),
                context=context,
            )
            if (
                metadata.ref.key != ref.key
                or metadata.ref.space != ref.space
                or metadata.ref.version is None
                or metadata.sha256 != hashlib.sha256(content).hexdigest()
            ):
                raise InvalidInput()
            source = ObjectReference(
                space=ref.space,
                key=ref.key,
                version=metadata.ref.version.value,
                sha256=metadata.sha256,
            )
            request = FileCleanseRequest(
                run_id=self.run_id,
                source=source,
                filename=filename,
                idempotency_key=nonce,
            )
            state = self._network(
                lambda: self._wait(request, states, context),
                cancellation_scope,
                context,
            )
            lookup = FileCleanseLookup(run_id=state.run_id, job_id=state.job_id)
            artifacts = self.artifacts(self.actor, lookup, source, state.artifact)
            try:
                data = read_verified_object(
                    artifacts,
                    ObjectRef(
                        state.artifact.space,
                        state.artifact.key,
                        Revision(state.artifact.version),
                    ),
                    sha256=state.artifact.sha256,
                    limit=self.max_bytes,
                    context=context,
                )
                artifact = CleanseArtifact.model_validate_json(data)
                if artifact.source != source:
                    raise InvalidInput()
                chunks = chunk_text(
                    artifact,
                    filename=filename,
                    strategy="basic",
                    max_characters=DEFAULT_MAXIMUM_CHUNK_SIZE,
                    new_after_n_chars=DEFAULT_EXPECTED_CHUNK_SIZE,
                    json_source=content,
                )
                text = "".join(chunk["content"] + "\n" for chunk in chunks).strip()
            finally:
                artifacts.close()
            receipt = self._network(
                lambda: self.client.release_file_cleanse(
                    lookup, self.actor.user_id, self.actor.tenant_id
                ),
                cancellation_scope,
                context,
            )
            if (
                receipt.run_id != lookup.run_id
                or receipt.job_id != lookup.job_id
                or receipt.released is not True
            ):
                raise InvalidInput()
            # Only this unique, single-writer staging key is removed after confirmed release.
            if objects.stat(metadata.ref, context=context).ref != metadata.ref:
                raise InvalidInput()
            objects.delete(
                ref if metadata.ref.version.value.startswith("etag:") else metadata.ref,
                context=context,
            )
            return text
        except BaseException:
            if states and states[0].status in {"queued", "running"}:
                state = states[0]
                try:
                    self._network(
                        lambda: self.client.cancel_file_cleanse(
                            FileCleanseLookup(run_id=self.run_id, job_id=state.job_id),
                            self.actor.user_id,
                            self.actor.tenant_id,
                        ),
                        None,
                        OperationContext(
                            context.operation_id + "-cancel", monotonic() + 10
                        ),
                    )
                except BaseException as error:  # noqa: BLE001 - Preserve the active failure during one cancellation.
                    logger.warning(
                        "run_file_cleanse_cancel_failed operation_id=%s exception_type=%s",
                        context.operation_id,
                        type(error).__name__,
                    )
            raise
        finally:
            objects.close()
