# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private completed-run cleanup grants do not expose source or cross-run access."""

from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import FileCleanseLookup
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import ObjectMetadata, ObjectRef, Revision

from infrastructure.file_processing.artifacts import RunCleanseArtifacts
from test.backend.services.test_cleanse_jobs import context, request


def make():
    port = Mock()
    lookup = FileCleanseLookup(run_id="a" * 32, job_id="b" * 32)
    source = request().source
    ref = ObjectRef(
        "files",
        f"run-cleanse/{lookup.run_id}/{lookup.job_id}/artifacts/{source.sha256}/{'c' * 64}.json",
        Revision("etag:1"),
    )
    return RunCleanseArtifacts(port, lookup, source), port, ref


@pytest.mark.parametrize("version", ["etag:1", "version:1"])
def test_cleanup_selects_storage_capability_without_conditional_delete_fallback(
    version,
):
    objects, port, ref = make()
    ref = ObjectRef(ref.space, ref.key, Revision(version))
    port.stat.return_value = ObjectMetadata(ref, 4, "application/json")
    objects.delete(ref, context=context())
    target = port.delete.call_args.args[0]
    assert target == (
        ref if version.startswith("version:") else ObjectRef(ref.space, ref.key)
    )
    port.delete.assert_called_once()


def test_replaced_object_is_not_deleted():
    objects, port, ref = make()
    port.stat.return_value = ObjectMetadata(
        ObjectRef(ref.space, ref.key, Revision("etag:replaced")), 4, "test"
    )
    with pytest.raises(Conflict):
        objects.delete(ref, context=context())
    port.delete.assert_not_called()


def test_versioned_cleanup_deletes_only_the_manifest_version():
    objects, port, ref = make()
    ref = ObjectRef(ref.space, ref.key, Revision("version:old"))
    ctx = context()
    objects.delete(ref, context=ctx)
    port.stat.assert_not_called()
    port.delete.assert_called_once_with(ref, context=ctx)


@pytest.mark.parametrize(
    "changed", ["source", "other-job", "other-run", "global", "unpinned", "space"]
)
def test_cleanup_cannot_read_or_delete_unowned_objects(changed):
    objects, port, ref = make()
    key, space, version = ref.key, ref.space, ref.version
    if changed == "source":
        key = request().source.key
    elif changed == "other-job":
        key = key.replace("b" * 32, "d" * 32)
    elif changed == "other-run":
        key = key.replace("a" * 32, "d" * 32)
    elif changed == "global":
        key = key.split("/", 3)[-1]
    elif changed == "unpinned":
        version = None
    else:
        space = "other"
    for action in (objects.stat, objects.open_read, objects.delete):
        with pytest.raises(ScopeDenied):
            action(ObjectRef(space, key, version), context=context())
    assert not port.mock_calls


def test_closed_capability_cannot_be_reused():
    objects, port, ref = make()
    objects.close()
    objects.close()
    port.close.assert_called_once()
    with pytest.raises(ScopeDenied):
        objects.delete(ref, context=context())
    port.delete.assert_not_called()
