# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned text projection for uploaded document cleansing."""

import hashlib
import io
import time

from contracts.agentos_knowledge import CleanseArtifact, CleanseBlock, ObjectReference
from nexent.storage.models import ObjectRef, OperationContext, Revision


def prepare_artifact(
    file_content: bytes,
    filename: str,
    source: ObjectReference,
    parser_version: str,
    *,
    parser,
    objects=None,
    context: OperationContext | None = None,
):
    """Extract structure and publish image blocks through the caller's scoped port."""
    if hashlib.sha256(file_content).hexdigest() != source.sha256:
        raise ValueError("Source checksum does not match")
    chunks, images = parser.file_process(
        file_data=file_content, filename=filename, chunking_strategy="none"
    )
    if images and (objects is None or context is None):
        raise ValueError("Image artifacts require the ObjectStore upload capability")
    blocks = []
    for chunk in chunks:
        if "content" not in chunk:
            raise ValueError("Parser returned a structural block without content")
        content = chunk["content"]
        blocks.append(
            CleanseBlock(
                ordinal=len(blocks),
                kind="text",
                content=content,
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                location=chunk.get("metadata") or {},
            )
        )
    for image in images:
        content = image.get("image_bytes")
        image_format = image.get("image_format", "png").lower()
        if (
            not isinstance(content, bytes)
            or not content
            or image_format not in {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}
        ):
            raise ValueError("Invalid extracted image")
        digest = hashlib.sha256(content).hexdigest()
        mime = "image/jpeg" if image_format == "jpg" else "image/" + image_format
        metadata = objects.put(
            ObjectRef(source.space, f"images/{source.sha256}/{digest}.{image_format}"),
            io.BytesIO(content),
            content_type=mime,
            size=len(content),
            context=context,
        )
        if metadata.sha256 != digest or metadata.ref.version is None:
            raise ValueError("Image publication was not confirmed")
        blocks.append(
            CleanseBlock(
                ordinal=len(blocks),
                kind="image",
                sha256=digest,
                object_ref=_object_reference(metadata),
                location=image.get("position") or {},
            )
        )
    return CleanseArtifact(source=source, parser_version=parser_version, blocks=blocks)


def _object_reference(metadata):
    if metadata.ref.version is None or metadata.sha256 is None:
        raise ValueError("Object publication requires a revision and checksum")
    return ObjectReference(
        space=metadata.ref.space,
        key=metadata.ref.key,
        version=metadata.ref.version.value,
        sha256=metadata.sha256,
    )


def cleanse_object(source, filename, parser_version, *, parser, objects, context):
    """Read an immutable source and publish the cross-service artifact by reference."""
    from contracts.constants.environment import MAX_KNOWLEDGE_FILE_SIZE_BYTES

    ref = ObjectRef(source.space, source.key, Revision(source.version))
    metadata = objects.stat(ref, context=context)
    if (
        metadata.ref.version != ref.version
        or not 0 <= metadata.size <= MAX_KNOWLEDGE_FILE_SIZE_BYTES
    ):
        raise ValueError("Invalid source revision or size")
    content = io.BytesIO()
    with objects.open_read(ref, context=context) as stream:
        remaining = metadata.size
        while remaining:
            context.remaining()
            part = stream.read(min(remaining, 1024 * 1024))
            if not part or len(part) > remaining:
                raise ValueError("Source size changed while reading")
            content.write(part)
            remaining -= len(part)
        if stream.read(1):
            raise ValueError("Source size changed while reading")
    context.remaining()
    artifact = prepare_artifact(
        content.getvalue(),
        filename,
        source,
        parser_version,
        parser=parser,
        objects=objects,
        context=context,
    )
    context.remaining()
    serialized = artifact.model_dump_json().encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    published = objects.put(
        ObjectRef(source.space, f"artifacts/{source.sha256}/{digest}.json"),
        io.BytesIO(serialized),
        content_type="application/json",
        size=len(serialized),
        context=context,
    )
    if published.sha256 != digest:
        raise ValueError("Artifact publication was not confirmed")
    return _object_reference(published)


def extract_uploaded_text(
    file_content, filename, chunking_strategy, *, parser, clock=time.time
):
    """Preserve the existing text endpoint result while injecting parser execution."""
    started = clock()
    chunks, _images = parser.file_process(
        file_data=file_content,
        filename=filename,
        chunking_strategy=chunking_strategy,
    )
    texts = [chunk["content"] for chunk in chunks if "content" in chunk]
    text = "".join(value + "\n" for value in texts).strip()
    return {
        "success": True,
        "task_id": None,
        "filename": filename,
        "text": text,
        "chunks": texts,
        "chunks_count": len(chunks),
        "text_length": len(text),
        "processing_time": clock() - started,
        "chunking_strategy": chunking_strategy,
    }
