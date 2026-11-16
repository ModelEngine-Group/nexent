# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run-bound text consumption and ownership across controlled storage/RPC ports."""

import asyncio
import hashlib
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    FileCleanseReleased,
    FileCleanseState,
    ObjectReference,
)
from nexent.core.concurrency import RunCancellationScope
from nexent.storage.errors import DeadlineExceeded, InvalidInput, OperationCancelled
from nexent.storage.models import ObjectRef, Revision
from runtime.text_cleanse import RunTextCleanser

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def setup_cleaner(mocker):
    actor = ServicePrincipal("user-a", "tenant-a")
    source = ObjectReference(
        space="files",
        key="workspace/user-a/" + "a" * 32 + "/outputs/analysis/fixture/file.txt",
        version="etag:source",
        sha256=hashlib.sha256(b"input").hexdigest(),
    )
    artifact = CleanseArtifact(
        source=source,
        parser_version="v2",
        blocks=[
            CleanseBlock(
                ordinal=0,
                kind="text",
                content="extracted",
                sha256=hashlib.sha256(b"extracted").hexdigest(),
                location={"element_type": "NarrativeText"},
            )
        ],
    )
    reference = ObjectReference(
        space="files",
        key="run-cleanse/"
        + "a" * 32
        + "/"
        + "b" * 32
        + "/artifacts/"
        + source.sha256
        + "/"
        + "c" * 64
        + ".json",
        version="etag:artifact",
        sha256="c" * 64,
    )
    state = FileCleanseState(
        run_id="a" * 32, job_id="b" * 32, status="completed", artifact=reference
    )
    client = SimpleNamespace(
        submit_file_cleanse=AsyncMock(return_value=state),
        inspect_file_cleanse=AsyncMock(return_value=state),
        release_file_cleanse=AsyncMock(
            return_value=FileCleanseReleased(run_id="a" * 32, job_id="b" * 32)
        ),
        cancel_file_cleanse=AsyncMock(),
    )
    stage, outputs = MagicMock(), MagicMock()
    stage.put.return_value = SimpleNamespace(
        ref=ObjectRef(source.space, source.key, Revision(source.version)),
        sha256=source.sha256,
    )
    stage.stat.return_value = stage.put.return_value
    stage_binding = MagicMock(return_value=(stage, ObjectRef(source.space, source.key)))
    output_binding = MagicMock(return_value=outputs)
    read = mocker.patch(
        "runtime.text_cleanse.read_verified_object",
        return_value=artifact.model_dump_json().encode(),
    )
    chunks = mocker.patch(
        "runtime.text_cleanse.chunk_text",
        return_value=[{"content": "one"}, {"content": "two"}],
    )
    cleaner = RunTextCleanser(
        actor,
        "a" * 32,
        client,
        max_bytes=10000,
        stage=stage_binding,
        artifacts=output_binding,
    )
    return SimpleNamespace(**locals())


def test_success_releases_before_deleting_only_its_staged_source(setup_cleaner):
    item = setup_cleaner
    order = []

    def release(*args):
        order.append("release")
        return FileCleanseReleased(run_id="a" * 32, job_id="b" * 32)

    item.client.release_file_cleanse.side_effect = release
    item.stage.delete.side_effect = lambda *args, **kwargs: order.append(
        "source-delete"
    )
    assert item.cleaner("file.txt", b"input") == "one\ntwo"
    assert order == ["release", "source-delete"]
    request = item.client.submit_file_cleanse.call_args.args[0]
    assert request.run_id == "a" * 32 and request.source == item.source
    assert item.client.submit_file_cleanse.call_args.args[1:] == ("user-a", "tenant-a")
    assert item.stage.delete.call_count == 1 and item.stage.delete.call_args.args == (
        ObjectRef("files", item.source.key),
    )
    item.stage.close.assert_called_once()
    item.outputs.close.assert_called_once()
    item.client.cancel_file_cleanse.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["source-checksum", "artifact-source", "release", "foreign-run"]
)
def test_unknown_or_invalid_results_keep_source_and_do_not_retry(
    setup_cleaner, failure
):
    item = setup_cleaner
    if failure == "source-checksum":
        item.stage.put.return_value.sha256 = "0" * 64
    elif failure == "artifact-source":
        artifact = item.artifact.model_copy(
            update={"source": item.source.model_copy(update={"sha256": "0" * 64})}
        )
        item.read.return_value = artifact.model_dump_json().encode()
    elif failure == "release":
        item.client.release_file_cleanse.side_effect = OSError("unknown-release")
    else:
        item.client.submit_file_cleanse.return_value = item.state.model_copy(
            update={"run_id": "d" * 32}
        )
    with pytest.raises((InvalidInput, OSError)):
        item.cleaner("file.txt", b"input")
    item.stage.delete.assert_not_called()
    assert item.client.submit_file_cleanse.call_count <= 1
    assert item.client.release_file_cleanse.call_count <= 1
    item.stage.close.assert_called_once()


def test_pre_cancelled_call_does_not_stage_or_call_management(setup_cleaner):
    item = setup_cleaner
    stop = Event()
    stop.set()
    with pytest.raises(OperationCancelled):
        item.cleaner(
            "file.txt", b"input", cancellation_scope=RunCancellationScope(stop)
        )
    item.stage_binding.assert_not_called()
    item.client.submit_file_cleanse.assert_not_called()


def test_total_deadline_cancels_known_job_once_without_removing_source(
    setup_cleaner, caplog
):
    item = setup_cleaner
    item.cleaner.seconds = 0.02
    item.client.submit_file_cleanse.return_value = FileCleanseState(
        run_id="a" * 32, job_id="b" * 32, status="queued"
    )
    with pytest.raises(DeadlineExceeded):
        item.cleaner("file.txt", b"input")
    assert (
        item.client.submit_file_cleanse.call_count
        == item.client.cancel_file_cleanse.call_count
        == 1
    )
    item.stage.delete.assert_not_called()
    item.client.release_file_cleanse.assert_not_called()
    assert (
        "run_file_cleanse_timeout" in caplog.text
        and "threshold_seconds=0.02" in caplog.text
    )
    assert "input" not in caplog.text


def test_submit_unknown_has_no_lookup_and_is_not_retried(setup_cleaner):
    item = setup_cleaner
    item.client.submit_file_cleanse.side_effect = OSError("unknown-submit")
    with pytest.raises(OSError, match="unknown-submit"):
        item.cleaner("file.txt", b"input")
    item.client.cancel_file_cleanse.assert_not_called()
    item.stage.delete.assert_not_called()
    assert item.client.submit_file_cleanse.call_count == 1


def test_scope_interrupts_network_and_unregisters_closer(setup_cleaner):
    item = setup_cleaner
    scope = RunCancellationScope()

    async def submit(*args):
        scope.cancel()
        await asyncio.Future()

    item.client.submit_file_cleanse.side_effect = submit
    with pytest.raises(OperationCancelled):
        item.cleaner("file.txt", b"input", cancellation_scope=scope)
    assert not scope._closers
    item.stage.delete.assert_not_called()
    item.stage.close.assert_called_once()


def test_scope_closer_is_removed_after_success_and_original_bytes_reach_chunker(
    setup_cleaner,
):
    item = setup_cleaner
    scope = RunCancellationScope()
    assert item.cleaner("file.txt", b"input", cancellation_scope=scope) == "one\ntwo"
    assert not scope._closers and not scope.cancelled
    assert item.chunks.call_args.kwargs["json_source"] == b"input"


def test_cancel_immediately_after_admission_still_cancels_known_job(setup_cleaner):
    item = setup_cleaner
    scope = RunCancellationScope()

    def submit(*args):
        scope.cancel()
        return FileCleanseState(run_id="a" * 32, job_id="b" * 32, status="queued")

    item.client.submit_file_cleanse.side_effect = submit
    with pytest.raises(OperationCancelled):
        item.cleaner("file.txt", b"input", cancellation_scope=scope)
    assert item.client.cancel_file_cleanse.call_count == 1
    item.stage.delete.assert_not_called()


@pytest.mark.parametrize("change", ["run", "source", "hash"])
def test_artifact_binding_rejects_foreign_paths_before_opening_a_client(
    setup_cleaner, mocker, change
):
    from contracts.agentos_knowledge import FileCleanseLookup
    from nexent.storage.errors import ScopeDenied

    from infrastructure.file_processing import text_objects

    item = setup_cleaner
    settings = mocker.patch.object(text_objects, "_configured_environment")
    ref = item.reference
    if change == "run":
        ref = ref.model_copy(update={"key": ref.key.replace("a" * 32, "d" * 32)})
    elif change == "source":
        ref = ref.model_copy(
            update={"key": ref.key.replace(item.source.sha256, "0" * 64)}
        )
    else:
        ref = ref.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ScopeDenied):
        text_objects.bind_text_artifact(
            item.actor,
            FileCleanseLookup(run_id="a" * 32, job_id="b" * 32),
            item.source,
            ref,
        )
    settings.assert_not_called()
