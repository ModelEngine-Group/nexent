# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cleansing cannot overwrite sources or access unrelated object grants."""

from io import BytesIO
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import FileCleanseLookup
from nexent.storage.errors import OutcomeUnknown, ScopeDenied
from nexent.storage.models import ObjectRef, Revision

from infrastructure.file_processing.objects import CleanseObjects
from test.backend.services.test_cleanse_jobs import context, request


@pytest.fixture
def ports():
    source = request().source
    inputs, outputs = Mock(), Mock()
    return CleanseObjects(source, inputs, outputs, context=context()), inputs, outputs


def test_read_is_pinned_to_one_source_revision(ports):
    store, inputs, _ = ports
    source = request().source
    ref = ObjectRef(source.space, source.key, Revision(source.version))
    store.stat(ref, context=context())
    inputs.stat.assert_called_once()
    for other in (
        ObjectRef(ref.space, ref.key),
        ObjectRef(ref.space, "other", ref.version),
    ):
        with pytest.raises(ScopeDenied):
            store.stat(other, context=context())
    inputs.stat.assert_called_once()


@pytest.mark.parametrize("kind,extension", [("artifacts", "json"), ("images", "png")])
def test_content_addressed_outputs_use_separate_tenant_store(ports, kind, extension):
    store, _, outputs = ports
    source = request().source
    key = f"{kind}/{source.sha256}/{'2' * 64}.{extension}"
    ref = ObjectRef(source.space, key)
    store.put(ref, BytesIO(b"data"), size=4, content_type="test", context=context())
    assert outputs.put.call_args.args[0] == ref


@pytest.mark.parametrize(
    "key",
    ["source.txt", "artifacts/other/hash.json", "images/" + "1" * 64 + "/other.png"],
)
def test_invalid_output_keys_never_reach_provider(ports, key):
    store, _, outputs = ports
    with pytest.raises(ScopeDenied):
        store.put(
            ObjectRef("files", key),
            BytesIO(b"data"),
            size=4,
            content_type="test",
            context=context(),
        )
    outputs.put.assert_not_called()


def test_close_attempts_both_stores_even_after_failure(ports):
    store, inputs, outputs = ports
    inputs.close.side_effect = RuntimeError("private detail")
    with pytest.raises(OutcomeUnknown):
        store.close()
    outputs.close.assert_called_once()


def test_closed_store_cannot_read_or_write(ports):
    store, inputs, outputs = ports
    store.close()
    store.close()
    inputs.close.assert_called_once()
    outputs.close.assert_called_once()
    source = request().source
    with pytest.raises(ScopeDenied):
        store.stat(
            ObjectRef(source.space, source.key, Revision(source.version)),
            context=context(),
        )


def test_run_output_capability_rejects_global_and_foreign_job_keys():
    source = request().source
    lookup = FileCleanseLookup(run_id="1" * 32, job_id="2" * 32)
    inputs, outputs = Mock(), Mock()
    store = CleanseObjects(source, inputs, outputs, context=context(), run=lookup)
    suffix = f"images/{source.sha256}/{'3' * 64}.png"
    own = f"run-cleanse/{lookup.run_id}/{lookup.job_id}/{suffix}"
    store.put(
        ObjectRef(source.space, own),
        BytesIO(b"image"),
        size=5,
        content_type="image/png",
        context=context(),
    )
    for key in (
        suffix,
        own.replace("2" * 32, "4" * 32),
        own.replace("1" * 32, "5" * 32),
    ):
        with pytest.raises(ScopeDenied):
            store.put(
                ObjectRef(source.space, key),
                BytesIO(b"image"),
                size=5,
                content_type="image/png",
                context=context(),
            )
    outputs.put.assert_called_once()
    inputs.stat.assert_not_called()


def test_invalid_run_scope_is_rejected_before_provider_io():
    inputs, outputs = Mock(), Mock()
    scope = FileCleanseLookup.model_construct(run_id="../other", job_id="2" * 32)
    with pytest.raises(ValueError):
        CleanseObjects(request().source, inputs, outputs, context=context(), run=scope)
    assert not inputs.mock_calls and not outputs.mock_calls
