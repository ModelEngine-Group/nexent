# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned text projection for uploaded document cleansing."""

import hashlib
import time

from contracts.agentos_knowledge import CleanseArtifact, CleanseBlock, ObjectReference


def prepare_text_artifact(
    file_content: bytes,
    filename: str,
    source: ObjectReference,
    parser_version: str,
    *,
    parser,
):
    """Extract structure without model-dependent retrieval chunking or storage I/O."""
    if hashlib.sha256(file_content).hexdigest() != source.sha256:
        raise ValueError("Source checksum does not match")
    chunks, images = parser.file_process(
        file_data=file_content, filename=filename, chunking_strategy="none"
    )
    if images:
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
    return CleanseArtifact(source=source, parser_version=parser_version, blocks=blocks)


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
