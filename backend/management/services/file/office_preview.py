# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management owns conversion; all managed-object I/O uses ObjectStore."""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import FILE_PREVIEW_SIZE_LIMIT
from contracts.constants.environment import LIBREOFFICE_PROFILE_DIR
from contracts.errors.exceptions import OfficeConversionException
from nexent.core.concurrency import (
    ManagedTaskSpec,
    get_current_thread_manager,
    get_default_thread_manager,
)
from nexent.storage.errors import StorageError
from nexent.storage.models import ByteRange, ObjectRef, OperationContext

from infrastructure.file_processing.conversion import convert_office_to_pdf_sync
from infrastructure.object_storage.composition import bind_preview_objects


def _convert(source, destination, temporary, *, store, context, profile_dir):
    """Keep files alive inside their managed worker even if the requester cancels."""
    with tempfile.TemporaryDirectory(prefix="office-preview-") as work:
        directory = Path(work)
        path = directory / Path(source.key).name
        metadata = store.stat(source, context=context)
        if metadata.size > FILE_PREVIEW_SIZE_LIMIT:
            raise OfficeConversionException("Source exceeds the preview size limit")
        with (
            store.open_read(metadata.ref, context=context) as stream,
            path.open("wb") as output,
        ):
            remaining = metadata.size
            while remaining:
                context.remaining()
                block = stream.read(min(1024 * 1024, remaining))
                if not block or len(block) > remaining:
                    raise OfficeConversionException("Source size changed while reading")
                output.write(block)
                remaining -= len(block)
        context.remaining()
        # A unique profile prevents one soffice instance accepting another job's input.
        profile = str(Path(profile_dir) / context.operation_id)
        try:
            pdf = Path(
                convert_office_to_pdf_sync(
                    str(path),
                    work,
                    min(30, context.remaining()),
                    profile_dir=profile,
                    cancelled=context.cancelled,
                )
            )
            context.remaining()
            if pdf.stat().st_size < 100:
                raise OfficeConversionException("Converted PDF is too small")
            with pdf.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise OfficeConversionException(
                        "Converted PDF has an invalid header"
                    )
                stream.seek(0)
                uploaded = store.put(
                    temporary,
                    stream,
                    content_type="application/pdf",
                    size=pdf.stat().st_size,
                    context=context,
                )
            with store.open_read(
                uploaded.ref, byte_range=ByteRange(0, 5), context=context
            ) as stream:
                if stream.read(5) != b"%PDF-":
                    raise OfficeConversionException(
                        "Uploaded PDF has an invalid header"
                    )
            # Copy only the exact version just validated, never an unqualified shared temp key.
            return store.copy(uploaded.ref, destination, context=context)
        finally:
            try:
                shutil.rmtree(profile)
            except FileNotFoundError:
                pass
            except OSError:
                logging.getLogger(__name__).warning(
                    "office_profile_cleanup_failed operation_id=%s",
                    context.operation_id,
                )


async def convert_preview(
    source_name, destination_name, *, timeout=120, manager=None, store=None
):
    """Use one deadline and one managed cancellation scope for the entire pipeline."""
    manager = manager or get_current_thread_manager() or get_default_thread_manager()
    if manager is None:
        raise RuntimeError("Office preview requires a service-owned ThreadManager")
    operation_id = uuid4().hex
    # Per-attempt keys prevent cancellation/cleanup from deleting another writer's object.
    temporary_name = destination_name + "." + operation_id + ".tmp"
    owns_store = store is None
    store = store or bind_preview_objects(
        frozenset({source_name, destination_name, temporary_name})
    )
    context = OperationContext(operation_id, monotonic() + timeout)

    def run(cancel_event):
        from dataclasses import replace

        bound = replace(context, cancelled=cancel_event)
        try:
            return _convert(
                ObjectRef("files", source_name),
                ObjectRef("files", destination_name),
                ObjectRef("files", temporary_name),
                store=store,
                context=bound,
                profile_dir=LIBREOFFICE_PROFILE_DIR,
            )
        finally:
            # Cleanup has its own small deadline and must also run after cancellation.
            cleanup = OperationContext(operation_id + "-cleanup", monotonic() + 5)
            try:
                store.delete(ObjectRef("files", temporary_name), context=cleanup)
            except StorageError:
                logging.getLogger(__name__).warning(
                    "office_preview_cleanup_failed operation_id=%s", operation_id
                )
            if owns_store:
                store.close()

    spec = ManagedTaskSpec(
        task_name="office-preview",
        owner="config",
        deadline_monotonic=context.deadline,
        pass_cancel_event=True,
    )
    async with asyncio.timeout(timeout):
        return await manager.run("office-conversion", spec, run)
