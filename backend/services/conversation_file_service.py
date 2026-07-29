import hashlib
import io
import json
import logging
import os
from functools import lru_cache
from typing import AsyncGenerator, Dict, List, Optional

from nexent.core.agents.agent_model import (
    ConversationFileComponent,
    FileMode,
    FilePreprocessConfig,
)

from database.attachment_db import delete_file, get_file_stream, upload_fileobj
from database.conversation_file_db import (
    ConversationFileStatus,
    create_conversation_file,
    delete_conversation_files,
    get_conversation_files,
    update_conversation_file_status,
)
from services.data_process_service import get_data_process_service
from services.vectordatabase_service import get_vector_db_core

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = {
    ".txt", ".pdf", ".docx", ".doc", ".html", ".htm", ".md", ".rtf",
    ".odt", ".pptx", ".ppt", ".json", ".epub", ".csv", ".xml",
    ".xlsx", ".xls",
}

FULLTEXT_CACHE_PREFIX = "conversation_file_cache"
CONV_FILE_INDEX_PREFIX = "conv_file_"

FILE_CITATION_RULES = (
    "You have access to the user's uploaded files enclosed in <uploaded_files> tags.\n"
    "Rules:\n"
    "1. When answering, ALWAYS cite the source file using【file_name】format.\n"
    "2. If information comes from multiple files, cite each source separately.\n"
    "3. NEVER combine or merge facts from different files into a single unsourced statement.\n"
    "4. If files contain conflicting information, present both versions with their respective sources."
)

def is_document_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in DOCUMENT_EXTENSIONS


def compute_file_hash(file_data: bytes) -> str:
    return hashlib.sha256(file_data).hexdigest()


def estimate_tokens(text: str) -> int:
    return len(text) * 2 // 3


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return text
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text
    char_limit = max_tokens * 3 // 2
    return text[:char_limit]


# ---------------------------------------------------------------------------
# Streaming file preprocessing with real-time SSE feedback
# ---------------------------------------------------------------------------


def _preprocess_sse(status: str, filename: str) -> str:
    payload = {
        "type": "preprocess",
        "content": json.dumps({"status": status, "filename": filename}, ensure_ascii=False),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _cleanup_stale_file(
    stale_record: dict,
    conversation_id: str,
    tenant_id: str,
    file_mode: FileMode,
) -> None:
    """Remove old chunks / fulltext cache when a file is re-uploaded with new content."""
    record_id = stale_record["id"]
    filename = stale_record.get("filename", "")

    if file_mode == FileMode.CHUNK_SEARCH:
        index_name = _get_conv_file_index_name(tenant_id)
        vdb_core = _get_vdb_core()
        if vdb_core.check_index_exists(index_name):
            try:
                body = {"query": {"bool": {"filter": [
                    {"term": {"conversation_id": conversation_id}},
                    {"term": {"content_hash": stale_record.get("content_hash", "")}},
                ]}}}
                result = vdb_core.client.delete_by_query(index=index_name, body=body)
                deleted = result.get("deleted", 0)
                if deleted:
                    logger.info("Cleaned %d stale chunks for %s", deleted, filename)
            except Exception as e:
                logger.warning("Failed to clean stale chunks for %s: %s", filename, e)
    else:
        fulltext_key = stale_record.get("fulltext_key")
        if fulltext_key:
            try:
                delete_file(fulltext_key)
            except Exception as e:
                logger.warning("Failed to delete stale fulltext cache %s: %s", fulltext_key, e)


async def preprocess_files_streaming(
    minio_files: List[dict],
    conversation_id: str,
    tenant_id: str,
    file_mode: FileMode = FileMode.FULL_TEXT_REFERENCE,
    embedding_model=None,
    user_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that preprocesses document files and yields SSE events
    in real-time so the frontend can show per-file progress.

    For FULL_TEXT_REFERENCE: extracts text and caches to MinIO.
    For CHUNK_SEARCH: extracts text, chunks, embeds and indexes to ES.
    """
    if not minio_files:
        return

    doc_files = [f for f in minio_files if is_document_file(f.get("name", ""))]
    if not doc_files:
        return

    existing_records = get_conversation_files(str(conversation_id))
    hash_to_record = {}
    name_to_record = {}
    for r in existing_records:
        if r["content_hash"]:
            hash_to_record[r["content_hash"]] = r
        name_to_record.setdefault(r["filename"], r)

    for f in doc_files:
        filename = f.get("name", "")
        stream = get_file_stream(f.get("object_name", ""))
        if stream is None:
            logger.warning("Cannot download file for preprocessing: %s", f.get("object_name"))
            yield _preprocess_sse("file_download_failed", filename)
            continue
        file_data = stream.read()
        content_hash = compute_file_hash(file_data)

        existing = hash_to_record.get(content_hash)
        if existing and existing["status"] in (ConversationFileStatus.READY, ConversationFileStatus.PENDING):
            yield _preprocess_sse("file_already_processed", filename)
            continue

        # Same filename but different content: clean up stale data and reuse the PG record
        stale = name_to_record.get(filename)
        reuse_stale = stale is not None and stale.get("content_hash") != content_hash
        if reuse_stale:
            _cleanup_stale_file(stale, conversation_id, tenant_id, file_mode)

        existing_id = stale["id"] if reuse_stale else (existing["id"] if existing else None)
        yield _preprocess_sse("file_processing", filename)

        if file_mode == FileMode.CHUNK_SEARCH:
            result = await _process_file_chunks(
                file_data, f, conversation_id, tenant_id, content_hash,
                embedding_model=embedding_model,
                existing_record_id=existing_id,
                user_id=user_id,
            )
        else:
            result = await _process_file_fulltext(
                file_data, f, conversation_id, tenant_id, content_hash,
                existing_record_id=existing_id,
                user_id=user_id,
            )

        if result and result.get("status") == ConversationFileStatus.READY:
            yield _preprocess_sse("file_processed", filename)
        else:
            yield _preprocess_sse("file_process_failed", filename)


def _create_or_reset_record(
    conversation_id: str,
    tenant_id: str,
    file_info: dict,
    content_hash: str,
    existing_record_id: Optional[int],
    user_id: Optional[str],
    file_mode: FileMode = FileMode.FULL_TEXT_REFERENCE,
) -> int:
    if existing_record_id:
        update_conversation_file_status(existing_record_id, ConversationFileStatus.PENDING, error_message=None)
        return existing_record_id
    record = create_conversation_file(
        conversation_id=str(conversation_id),
        tenant_id=tenant_id,
        object_name=file_info.get("object_name", ""),
        filename=file_info.get("name", ""),
        content_hash=content_hash,
        user_id=user_id,
        file_mode=file_mode.value,
    )
    return record["id"]


async def _process_file_fulltext(
    file_data: bytes,
    file_info: dict,
    conversation_id: str,
    tenant_id: str,
    content_hash: str,
    existing_record_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Optional[dict]:
    filename = file_info.get("name", "")
    record_id = _create_or_reset_record(
        conversation_id, tenant_id, file_info, content_hash,
        existing_record_id, user_id, FileMode.FULL_TEXT_REFERENCE,
    )

    try:
        service = get_data_process_service()
        result = await service.process_uploaded_text_file(
            file_content=file_data,
            filename=filename,
            chunking_strategy="none",
        )
        text = result.get("text", "")

        text_bytes = text.encode("utf-8")
        upload_result = upload_fileobj(
            file_obj=io.BytesIO(text_bytes),
            file_name=f"{filename}.txt",
            prefix=FULLTEXT_CACHE_PREFIX,
            generate_presigned_url=False,
        )
        if not upload_result.get("success"):
            logger.error("Failed to upload fulltext cache for %s", filename)
            update_conversation_file_status(record_id, ConversationFileStatus.FAILED, error_message="Fulltext cache upload failed")
            return None

        actual_key = upload_result["object_name"]
        update_conversation_file_status(record_id, ConversationFileStatus.READY, fulltext_key=actual_key)

        logger.info(
            "Conversation file processed (fulltext): %s (tokens~%d, cache=%s)",
            filename, estimate_tokens(text), actual_key,
        )
        return {"id": record_id, "filename": filename, "status": ConversationFileStatus.READY}

    except Exception as e:
        logger.error("Failed to process conversation file %s: %s", filename, str(e))
        update_conversation_file_status(record_id, ConversationFileStatus.FAILED, error_message=str(e))
        return None


async def _process_file_chunks(
    file_data: bytes,
    file_info: dict,
    conversation_id: str,
    tenant_id: str,
    content_hash: str,
    embedding_model=None,
    existing_record_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Optional[dict]:
    filename = file_info.get("name", "")
    if embedding_model is None:
        logger.error("Chunk search requires an embedding model but got None for %s", filename)
        return None

    record_id = _create_or_reset_record(
        conversation_id, tenant_id, file_info, content_hash,
        existing_record_id, user_id, FileMode.CHUNK_SEARCH,
    )

    try:
        service = get_data_process_service()
        result = await service.process_uploaded_text_file(
            file_content=file_data,
            filename=filename,
            chunking_strategy="basic",
        )
        chunk_texts = result.get("chunks", [])
        if not chunk_texts:
            update_conversation_file_status(record_id, ConversationFileStatus.FAILED, error_message="No chunks produced")
            return None

        index_name = _get_conv_file_index_name(tenant_id)
        vdb_core = _get_vdb_core()

        if not vdb_core.check_index_exists(index_name):
            embedding_dim = getattr(embedding_model, "embedding_dim", None) or 1024
            vdb_core.create_index(index_name, embedding_dim=embedding_dim)
            vdb_core.client.indices.put_mapping(
                index=index_name,
                body={"properties": {
                    "conversation_id": {"type": "keyword"},
                    "content_hash": {"type": "keyword"},
                }},
            )
            logger.info("Created conversation file index: %s", index_name)

        documents = []
        for chunk_text in chunk_texts:
            doc = {
                "content": chunk_text,
                "path_or_url": f"conv://{conversation_id}/{filename}",
                "conversation_id": conversation_id,
                "filename": filename,
                "content_hash": content_hash,
            }
            documents.append(doc)

        indexed_count = vdb_core.vectorize_documents(
            index_name=index_name,
            embedding_model=embedding_model,
            documents=documents,
        )

        update_conversation_file_status(
            record_id, ConversationFileStatus.READY,
            chunk_count=indexed_count,
            embedding_model=getattr(embedding_model, "model", None),
        )

        logger.info(
            "Conversation file processed (chunk_search): %s (%d chunks indexed to %s)",
            filename, indexed_count, index_name,
        )
        return {"id": record_id, "filename": filename, "status": ConversationFileStatus.READY}

    except Exception as e:
        logger.error("Failed to process conversation file chunks %s: %s", filename, str(e))
        update_conversation_file_status(record_id, ConversationFileStatus.FAILED, error_message=str(e))
        return None


# ---------------------------------------------------------------------------
# Context building: ConversationFileComponent assembly
# ---------------------------------------------------------------------------


def _get_conv_file_index_name(tenant_id: str) -> str:
    return f"{CONV_FILE_INDEX_PREFIX}{tenant_id}"


def _get_vdb_core():
    return get_vector_db_core()



@lru_cache(maxsize=128)
def _read_fulltext_cache(fulltext_key: str) -> Optional[str]:
    stream = get_file_stream(fulltext_key)
    if stream is None:
        return None
    return stream.read().decode("utf-8")


def build_conversation_file_component(
    conversation_id: str,
    file_preprocess_config: FilePreprocessConfig,
) -> Optional[ConversationFileComponent]:
    all_records = get_conversation_files(str(conversation_id))
    ready_records = [r for r in all_records if r["status"] == ConversationFileStatus.READY and r["fulltext_key"]]

    if not ready_records:
        return None

    max_parse = file_preprocess_config.max_parse_length
    max_total = file_preprocess_config.prompt_max_token_length

    file_sections: List[str] = []
    filenames: List[str] = []
    used_tokens = 0

    for idx, r in enumerate(ready_records, 1):
        text = _read_fulltext_cache(r["fulltext_key"])
        if text is None:
            continue

        truncated = _truncate_to_tokens(text, max_parse)
        section = f'<file name="{r["filename"]}" id="file_{idx}">\n{truncated}\n</file>'
        section_tokens = estimate_tokens(section)
        if used_tokens + section_tokens > max_total and file_sections:
            break
        file_sections.append(section)
        filenames.append(r["filename"])
        used_tokens += section_tokens

    if not file_sections:
        return None

    joined = "\n\n".join(file_sections)
    content = f"<uploaded_files>\n\n{joined}\n\n</uploaded_files>"

    return ConversationFileComponent(
        content=content,
        filenames=filenames,
    )


def retrieve_conversation_chunks(
    query: str,
    conversation_id: str,
    tenant_id: str,
    file_preprocess_config: FilePreprocessConfig,
    embedding_model=None,
    rerank_model=None,
) -> Optional[ConversationFileComponent]:
    index_name = _get_conv_file_index_name(tenant_id)
    vdb_core = _get_vdb_core()

    if not vdb_core.check_index_exists(index_name):
        return None

    top_k = file_preprocess_config.rerank_top_n
    try:
        results = vdb_core.semantic_search(
            index_names=[index_name],
            query_text=query,
            embedding_model=embedding_model,
            top_k=top_k * 3 if rerank_model else top_k,
        )
    except Exception as e:
        logger.error("Conversation chunk search failed: %s", e)
        return None

    conv_results = [r for r in results if r.get("document", {}).get("conversation_id") == conversation_id]

    if not conv_results:
        return None

    if rerank_model:
        try:
            texts = [r["document"]["content"] for r in conv_results]
            reranked = rerank_model.rerank(query, texts, top_k=top_k)
            conv_results = [conv_results[r["index"]] for r in reranked]
        except Exception as e:
            logger.warning("Rerank failed, using semantic search results: %s", e)
            conv_results = conv_results[:top_k]

    file_sections = []
    filenames = set()
    used_tokens = 0
    for idx, r in enumerate(conv_results, 1):
        doc = r.get("document", {})
        filename = doc.get("filename", "unknown")
        content = doc.get("content", "")
        filenames.add(filename)
        section = f'<chunk source="{filename}" id="chunk_{idx}">\n{content}\n</chunk>'
        section_tokens = estimate_tokens(section)
        if used_tokens + section_tokens > file_preprocess_config.prompt_max_token_length and file_sections:
            break
        file_sections.append(section)
        used_tokens += section_tokens

    if not file_sections:
        return None

    joined = "\n\n".join(file_sections)
    xml_content = f"<retrieved_chunks>\n\n{joined}\n\n</retrieved_chunks>"

    return ConversationFileComponent(
        content=xml_content,
        filenames=list(filenames),
    )


# ---------------------------------------------------------------------------
# Cleanup: delete MinIO caches + ES chunks + soft-delete PG records
# ---------------------------------------------------------------------------


def cleanup_conversation_chunks(conversation_id: str, tenant_id: str) -> None:
    index_name = _get_conv_file_index_name(tenant_id)
    vdb_core = _get_vdb_core()
    if not vdb_core.check_index_exists(index_name):
        return
    try:
        result = vdb_core.client.delete_by_query(
            index=index_name,
            body={"query": {"term": {"conversation_id": conversation_id}}},
        )
        deleted = result.get("deleted", 0)
        if deleted > 0:
            logger.info("Deleted %d chunks from %s for conversation %s", deleted, index_name, conversation_id)
    except Exception as e:
        logger.warning("Failed to clean up conversation chunks for %s: %s", conversation_id, e)


def cleanup_conversation_files(conversation_id: str, tenant_id: str = "") -> None:
    records = get_conversation_files(str(conversation_id))
    for r in records:
        if r.get("fulltext_key"):
            try:
                delete_file(r["fulltext_key"])
            except Exception as e:
                logger.warning("Failed to delete fulltext cache %s: %s", r["fulltext_key"], e)

    count = delete_conversation_files(str(conversation_id))
    if count > 0:
        logger.info("Cleaned up %d conversation file records for conversation %s", count, conversation_id)

    if tenant_id:
        cleanup_conversation_chunks(conversation_id, tenant_id)
