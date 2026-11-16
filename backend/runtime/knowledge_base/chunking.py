# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Final text/table chunking; image blocks remain owned by the image execution stage."""

import hashlib

from contracts.agentos_knowledge import CleanseArtifact


def _document(content, filename, *, index=None, element_type=None, metadata=None):
    result = {"content": content, "filename": filename}
    metadata = metadata or {}
    if index is not None:
        result["metadata"] = {"chunk_index": index, "element_type": element_type}
        for field in ("page_number", "coordinates"):
            if field in metadata:
                result["metadata"][field] = metadata[field]
    languages = metadata.get("languages")
    if languages:
        result["language"] = languages[0]
    return result


def chunk_text(
    artifact, *, filename, strategy, max_characters, new_after_n_chars, json_source=None
):
    if (
        not isinstance(artifact, CleanseArtifact)
        or not isinstance(filename, str)
        or not filename
        or strategy not in {"basic", "by_title", "none"}
        or type(max_characters) is not int
        or max_characters < 1
        or type(new_after_n_chars) is not int
        or new_after_n_chars < 1
    ):
        raise ValueError("Invalid text chunking request")
    blocks = [block for block in artifact.blocks if block.kind != "image"]
    if filename.lower().endswith(".json"):
        from nexent.data_process.json_chunk_processor import JSONChunkProcessor

        if (
            len(blocks) != 1
            or blocks[0].location.get("element_type") != "JSONSource"
            or not isinstance(json_source, bytes)
            or hashlib.sha256(json_source).hexdigest() != artifact.source.sha256
        ):
            raise ValueError("JSON chunking requires the pinned source")
        texts = [
            value
            for value in JSONChunkProcessor(max_characters).split(json_source)
            if value and value.strip()
        ]
        if strategy == "none":
            return [_document("\n\n".join(texts), filename)]
        return [
            _document(value, filename, index=index, element_type="CompositeElement")
            for index, value in enumerate(texts)
        ]
    if filename.lower().endswith((".xlsx", ".xls")):
        return [
            {
                "content": block.content,
                "filename": filename,
                "metadata": {
                    key: value
                    for key, value in block.location.items()
                    if key != "filename"
                },
            }
            for block in blocks
        ]
    if strategy == "none":
        return [
            _document(
                "\n\n".join(block.content for block in blocks),
                filename,
                metadata=blocks[0].location if blocks else {},
            )
        ]
    from nexent.data_process.base import STRUCTURE_METADATA_FIELDS
    from unstructured.chunking.basic import chunk_elements
    from unstructured.chunking.title import chunk_by_title
    from unstructured.documents.elements import (
        TYPE_TO_TEXT_ELEMENT_MAP,
        CoordinatesMetadata,
        ElementMetadata,
    )

    elements = []
    for block in blocks:
        element_class = TYPE_TO_TEXT_ELEMENT_MAP.get(block.location.get("element_type"))
        if element_class is None:
            raise ValueError("Unsupported structural element")
        metadata = {
            key: block.location[key]
            for key in STRUCTURE_METADATA_FIELDS
            if key in block.location
        }
        if "coordinates" in metadata:
            metadata["coordinates"] = CoordinatesMetadata.from_dict(
                metadata["coordinates"]
            )
        elements.append(
            element_class(text=block.content, metadata=ElementMetadata(**metadata))
        )
    chunker = chunk_elements if strategy == "basic" else chunk_by_title
    chunks = chunker(
        elements,
        max_characters=max_characters,
        new_after_n_chars=new_after_n_chars,
        include_orig_elements=False,
    )
    result = []
    for index, element in enumerate(chunks):
        metadata = {
            name: getattr(element.metadata, name)
            for name in ("page_number", "languages", "coordinates")
            if getattr(element.metadata, name) is not None
        }
        if "coordinates" in metadata:
            metadata["coordinates"] = metadata["coordinates"].to_dict()
        result.append(
            _document(
                element.text,
                filename,
                index=index,
                element_type=type(element).__name__,
                metadata=metadata,
            )
        )
    return result
