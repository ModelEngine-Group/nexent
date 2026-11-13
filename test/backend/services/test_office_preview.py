# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management conversion owns resources and never calls the retired HTTP service."""

import io
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from time import monotonic
from unittest.mock import MagicMock

import pytest
from contracts.errors.exceptions import OfficeConversionException
from management.services.file import office_preview
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.storage.errors import NotFound
from nexent.storage.models import ObjectMetadata, ObjectRef, OperationContext, Revision


@pytest.fixture
def setup(mocker):
    store = MagicMock()
    source = ObjectRef("files", "docs/report.docx")
    destination = ObjectRef("files", "preview/final.pdf")
    temporary = ObjectRef("files", "preview/attempt.pdf")
    pdf = b"%PDF-" + b"x" * 100
    store.stat.return_value = ObjectMetadata(
        ObjectRef(source.space, source.key, Revision("etag:source")),
        3,
        "application/msword",
    )
    streams = []

    @contextmanager
    def read(ref, **kwargs):
        stream = io.BytesIO(b"doc" if ref.key == source.key else pdf[:5])
        streams.append(stream)
        try:
            yield stream
        finally:
            stream.close()

    store.open_read.side_effect = read
    store.put.return_value = ObjectMetadata(
        ObjectRef("files", temporary.key, Revision("etag:uploaded")),
        len(pdf),
        "application/pdf",
    )
    paths = []

    def convert(input_path, output_dir, timeout, *, profile_dir, cancelled):
        assert Path(input_path).read_bytes() == b"doc"
        assert 0 < timeout <= 30
        paths.append(Path(output_dir))
        path = Path(output_dir) / "report.pdf"
        path.write_bytes(pdf)
        return str(path)

    converter = mocker.patch.object(
        office_preview, "convert_office_to_pdf_sync", side_effect=convert
    )
    return store, source, destination, temporary, streams, paths, converter


def execute(setup, **kwargs):
    store, source, destination, temporary, *_ = setup
    return office_preview._convert(
        source,
        destination,
        temporary,
        store=store,
        context=OperationContext("op", monotonic() + 5),
        profile_dir=kwargs.pop("profile_dir"),
        **kwargs,
    )


def test_versioned_source_and_upload_are_used_and_files_closed(setup, tmp_path):
    store, _, destination, _, streams, paths, _ = setup
    execute(setup, profile_dir=str(tmp_path))
    assert all(s.closed for s in streams)
    assert all(not p.exists() for p in paths)
    source_ref = store.open_read.call_args_list[0].args[0]
    assert source_ref.version == Revision("etag:source")
    uploaded = store.put.return_value.ref
    store.copy.assert_called_once_with(
        uploaded, destination, context=store.copy.call_args.kwargs["context"]
    )


@pytest.mark.parametrize(
    "failure", ["missing", "source_size", "convert", "bad_header", "upload", "copy"]
)
def test_failure_never_claims_success_and_closes_resources(setup, tmp_path, failure):
    store, *_rest, converter = setup
    if failure == "missing":
        store.stat.side_effect = NotFound()
    elif failure == "source_size":
        store.stat.return_value = ObjectMetadata(
            ObjectRef("files", "docs/report.docx"), 10, "application/msword"
        )
    elif failure == "convert":
        converter.side_effect = TimeoutError("converter deadline")
    elif failure == "bad_header":

        def invalid(input_path, output_dir, *args, **kwargs):
            result = Path(output_dir) / "report.pdf"
            result.write_bytes(b"not-a-pdf" * 20)
            return str(result)

        converter.side_effect = invalid
    elif failure == "upload":
        store.put.side_effect = RuntimeError("storage unavailable")
    else:
        store.copy.side_effect = RuntimeError("copy failed")
    with pytest.raises(
        (NotFound, OfficeConversionException, RuntimeError, TimeoutError)
    ):
        execute(setup, profile_dir=str(tmp_path))
    assert all(s.closed for s in setup[4])
    assert all(not p.exists() for p in setup[5])
    if failure not in {"copy"}:
        store.copy.assert_not_called()


def test_profile_cleanup_failure_is_observable(setup, tmp_path, mocker, caplog):
    original = office_preview.shutil.rmtree

    def cleanup(path, *args, **kwargs):
        if str(path) == str(tmp_path / "op"):
            raise PermissionError("fixture cleanup failure")
        return original(path, *args, **kwargs)

    mocker.patch.object(office_preview.shutil, "rmtree", side_effect=cleanup)
    execute(setup, profile_dir=str(tmp_path))
    assert "office_profile_cleanup_failed operation_id=op" in caplog.text


@pytest.mark.asyncio
async def test_conversion_requires_service_owned_manager(mocker):
    mocker.patch.object(office_preview, "get_current_thread_manager", return_value=None)
    mocker.patch.object(office_preview, "get_default_thread_manager", return_value=None)
    bind = mocker.patch.object(office_preview, "bind_preview_objects")
    with pytest.raises(RuntimeError, match="service-owned"):
        await office_preview.convert_preview("a", "b")
    bind.assert_not_called()


@pytest.mark.asyncio
async def test_deadline_cancels_worker_without_deleting_source(mocker):
    manager = ThreadManager(
        "preview-test",
        {
            "office-conversion": LanePolicy(
                "office-conversion",
                max_workers=1,
                max_queue_size=1,
                queue_timeout_seconds=1,
                cancel_grace_seconds=0.1,
                shutdown_grace_seconds=1,
            )
        },
    )
    manager.start()
    exited = Event()
    store = MagicMock()

    def convert(*args, store, context, **kwargs):
        while not context.cancelled.is_set():
            exited.wait(0.005)
        exited.set()
        context.remaining()

    mocker.patch.object(office_preview, "_convert", side_effect=convert)
    try:
        with pytest.raises(TimeoutError):
            await office_preview.convert_preview(
                "source.docx", "final.pdf", timeout=0.1, manager=manager, store=store
            )
    finally:
        result = await manager.shutdown(timeout=1)
        assert not result.stuck_execution_ids
    assert exited.is_set()
    deleted = store.delete.call_args.args[0].key
    assert deleted.startswith("final.pdf.") and deleted.endswith(".tmp")
    assert deleted not in {"source.docx", "final.pdf"}


@pytest.mark.asyncio
async def test_cache_lock_is_shared_by_waiters_and_late_arrivals(mocker):
    import asyncio

    from management.services.file import preview

    entered = asyncio.Event()
    release = asyncio.Event()
    ready = False

    async def convert(*args):
        nonlocal ready
        entered.set()
        await release.wait()
        ready = True

    mocker.patch.object(preview, "_is_pdf_cache_valid", side_effect=lambda _: ready)
    conversion = mocker.patch.object(preview, "convert_preview", side_effect=convert)
    first = asyncio.create_task(
        preview._convert_office_to_cached_pdf("docs/same.docx", "preview/same.pdf")
    )
    await entered.wait()
    second = asyncio.create_task(
        preview._convert_office_to_cached_pdf("docs/same.docx", "preview/same.pdf")
    )
    await asyncio.sleep(0)
    shared = preview._conversion_locks["docs/same.docx"]
    release.set()
    await first
    third = asyncio.create_task(
        preview._convert_office_to_cached_pdf("docs/same.docx", "preview/same.pdf")
    )
    await asyncio.gather(second, third)
    conversion.assert_awaited_once()
    assert not shared.locked()
