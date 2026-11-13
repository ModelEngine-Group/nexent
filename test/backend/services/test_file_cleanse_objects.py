# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cleansing artifacts use immutable sources and checked ObjectStore publications."""

import hashlib
import io
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import CleanseArtifact, ObjectReference
from management.services.file.cleanse import cleanse_object
from nexent.storage.models import ObjectMetadata, ObjectRef, OperationContext, Revision


class Store:
    def __init__(self):
        self.data = {"source.txt": b"source"}
        self.readers = []
        self.writes = []
        self.metadata = ObjectMetadata(
            ObjectRef("cleanse", "source.txt", Revision("etag:source")), 6, "text/plain"
        )

    def stat(self, ref, *, context):
        return self.metadata

    @contextmanager
    def open_read(self, ref, *, context):
        stream = io.BytesIO(self.data[ref.key])
        self.readers.append(stream)
        try:
            yield stream
        finally:
            stream.close()

    def put(self, ref, stream, *, content_type, size, context):
        value = stream.read()
        assert len(value) == size
        self.data[ref.key] = value
        self.writes.append(ref.key)
        return ObjectMetadata(
            ObjectRef(ref.space, ref.key, Revision("etag:published")),
            size,
            content_type,
            sha256=hashlib.sha256(value).hexdigest(),
        )


def source():
    return ObjectReference(
        space="cleanse",
        key="source.txt",
        version="etag:source",
        sha256=hashlib.sha256(b"source").hexdigest(),
    )


def run(store, parser):
    return cleanse_object(
        source(),
        "source.txt",
        "parser-1",
        parser=parser,
        objects=store,
        context=OperationContext("cleanse", monotonic() + 5),
    )


def test_images_and_text_are_published_by_reference():
    store = Store()
    parser = SimpleNamespace(
        file_process=Mock(
            return_value=(
                [{"content": "paragraph", "metadata": {"page_number": 2}}],
                [
                    {
                        "image_bytes": b"image",
                        "image_format": "PNG",
                        "position": {"page_number": 2},
                    }
                ],
            )
        )
    )
    result = run(store, parser)
    artifact = CleanseArtifact.model_validate_json(store.data[result.key])
    assert [block.kind for block in artifact.blocks] == ["text", "image"]
    assert artifact.blocks[1].location == {"page_number": 2}
    image = artifact.blocks[1].object_ref
    assert store.data[image.key] == b"image"
    assert image.version == "etag:published"
    assert image.sha256 == hashlib.sha256(b"image").hexdigest()
    assert result.sha256 == hashlib.sha256(store.data[result.key]).hexdigest()
    assert all(stream.closed for stream in store.readers)
    assert parser.file_process.call_args.kwargs["chunking_strategy"] == "none"
    assert result.key.startswith("artifacts/")


@pytest.mark.parametrize("failure", ["hash", "short", "long", "version", "size"])
def test_invalid_source_never_reaches_parser_or_writes(failure):
    store = Store()
    parser = SimpleNamespace(file_process=Mock())
    if failure == "hash":
        store.data["source.txt"] = b"change"
    elif failure == "short":
        store.data["source.txt"] = b"short"
    elif failure == "long":
        store.data["source.txt"] = b"source-extra"
    else:
        store.metadata = ObjectMetadata(
            ObjectRef(
                "cleanse",
                "source.txt",
                Revision("etag:other" if failure == "version" else "etag:source"),
            ),
            -1 if failure == "size" else 6,
            "text/plain",
        )
    with pytest.raises(ValueError):
        run(store, parser)
    parser.file_process.assert_not_called()
    assert not store.writes
    assert all(stream.closed for stream in store.readers)


def test_invalid_image_does_not_publish_artifact():
    store = Store()
    parser = SimpleNamespace(
        file_process=Mock(
            return_value=([], [{"image_bytes": b"image", "image_format": "exe"}])
        )
    )
    with pytest.raises(ValueError, match="Invalid extracted image"):
        run(store, parser)
    assert not store.writes


def test_unconfirmed_image_never_becomes_an_artifact(mocker):
    store = Store()
    parser = SimpleNamespace(
        file_process=Mock(
            return_value=([], [{"image_bytes": b"image", "image_format": "png"}])
        )
    )
    write = mocker.patch.object(
        store,
        "put",
        return_value=ObjectMetadata(
            ObjectRef("cleanse", "image", Revision("etag:image")),
            5,
            "image/png",
            sha256="0" * 64,
        ),
    )
    with pytest.raises(ValueError, match="not confirmed"):
        run(store, parser)
    write.assert_called_once()


def test_unconfirmed_artifact_is_rejected(mocker):
    store = Store()
    parser = SimpleNamespace(
        file_process=Mock(return_value=([{"content": "text"}], []))
    )
    mocker.patch.object(
        store,
        "put",
        return_value=ObjectMetadata(
            ObjectRef("cleanse", "artifact", Revision("etag:artifact")),
            5,
            "application/json",
            sha256="0" * 64,
        ),
    )
    with pytest.raises(ValueError, match="not confirmed"):
        run(store, parser)
