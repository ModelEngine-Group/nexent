import hashlib
import io
import json
import logging
import os
from typing import AsyncGenerator, Dict, List, Optional

from nexent.core.agents.agent_model import FilePreprocessConfig

from database.attachment_db import delete_file, get_file_stream, upload_fileobj
from database.conversation_file_db import (
    ConversationFileStatus,
    create_conversation_file,
    delete_conversation_files,
    get_conversation_files,
    update_conversation_file_status,
)
from services.data_process_service import get_data_process_service

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = {
    ".txt", ".pdf", ".docx", ".doc", ".html", ".htm", ".md", ".rtf",
    ".odt", ".pptx", ".ppt", ".json", ".epub", ".csv", ".xml",
    ".xlsx", ".xls",
}

FULLTEXT_CACHE_PREFIX = "conversation_file_cache"


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
    payload = {"type": "preprocess", "content": json.dumps({"status": status, "filename": filename}, ensure_ascii=False)}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def preprocess_files_streaming(
    minio_files: List[dict],
    conversation_id: str,
    tenant_id: str,
    user_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that preprocesses document files and yields SSE events
    in real-time so the frontend can show per-file progress.

    Results are persisted to DB; callers should invoke assemble_fulltext_query
    afterwards to build the prompt from cached data.
    """
    if not minio_files:
        return

    doc_files = [f for f in minio_files if is_document_file(f.get("name", ""))]
    if not doc_files:
        return

    existing_records = get_conversation_files(str(conversation_id))
    hash_to_record = {}
    for r in existing_records:
        if r["content_hash"]:
            hash_to_record[r["content_hash"]] = r

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

        existing_id = existing["id"] if existing else None
        yield _preprocess_sse("file_processing", filename)
        result = await _process_file_data(
            file_data, f, conversation_id, tenant_id, content_hash,
            existing_record_id=existing_id,
            user_id=user_id,
        )
        if result and result.get("status") == ConversationFileStatus.READY:
            yield _preprocess_sse("file_processed", filename)
        else:
            yield _preprocess_sse("file_process_failed", filename)


async def _process_file_data(
    file_data: bytes,
    file_info: dict,
    conversation_id: str,
    tenant_id: str,
    content_hash: str,
    existing_record_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Optional[dict]:
    object_name = file_info.get("object_name", "")
    filename = file_info.get("name", "")

    if existing_record_id:
        record_id = existing_record_id
        update_conversation_file_status(record_id, ConversationFileStatus.PENDING, error_message=None)
    else:
        record = create_conversation_file(
            conversation_id=str(conversation_id),
            tenant_id=tenant_id,
            object_name=object_name,
            filename=filename,
            content_hash=content_hash,
            user_id=user_id,
        )
        record_id = record["id"]

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
            "Conversation file processed: %s (tokens~%d, cache=%s)",
            filename, estimate_tokens(text), actual_key,
        )
        return {
            "id": record_id,
            "filename": filename,
            "status": ConversationFileStatus.READY,
            "fulltext_key": actual_key,
        }

    except Exception as e:
        logger.error("Failed to process conversation file %s: %s", filename, str(e))
        update_conversation_file_status(record_id, ConversationFileStatus.FAILED, error_message=str(e))
        return None


# ---------------------------------------------------------------------------
# Context building: read cached fulltext → assemble XML prompt
# Only called when file_mode == FULL_TEXT_REFERENCE at query time.
# ---------------------------------------------------------------------------


def build_fulltext_context(
    file_texts: Dict[str, str],
    query: str,
    max_parse_length: int = 2000,
    prompt_max_token_length: int = 5000,
) -> str:
    file_sections = []
    used_tokens = 0
    for idx, (filename, text) in enumerate(file_texts.items(), 1):
        truncated = _truncate_to_tokens(text, max_parse_length)
        section = f'<file name="{filename}" id="file_{idx}">\n{truncated}\n</file>'
        section_tokens = estimate_tokens(section)
        if used_tokens + section_tokens > prompt_max_token_length and file_sections:
            break
        file_sections.append(section)
        used_tokens += section_tokens

    joined = "\n\n".join(file_sections)

    return (
        "<uploaded_files>\n\n"
        f"{joined}\n\n"
        "</uploaded_files>\n\n"
        "You have access to the user's uploaded files enclosed in <uploaded_files> tags.\n"
        "Rules:\n"
        "1. When answering, ALWAYS cite the source file using【file_name】format.\n"
        "2. If information comes from multiple files, cite each source separately.\n"
        "3. NEVER combine or merge facts from different files into a single unsourced statement.\n"
        "4. If files contain conflicting information, present both versions with their respective sources.\n\n"
        f"User question: {query}"
    )


def assemble_fulltext_query(
    query: str,
    conversation_id: str,
    file_preprocess_config: FilePreprocessConfig,
) -> str:
    """
    Read all ready fulltext caches for a conversation and assemble the
    XML-tagged context prompt. Called at query time when file_mode is
    FULL_TEXT_REFERENCE.

    Returns the modified query with file content injected, or the original
    query unchanged if no files are available.
    """
    all_records = get_conversation_files(str(conversation_id))
    ready_records = [r for r in all_records if r["status"] == ConversationFileStatus.READY and r["fulltext_key"]]

    if not ready_records:
        return query

    file_texts: Dict[str, str] = {}
    for r in ready_records:
        cached_stream = get_file_stream(r["fulltext_key"])
        if cached_stream is None:
            continue
        file_texts[r["filename"]] = cached_stream.read().decode("utf-8")

    if not file_texts:
        return query

    return build_fulltext_context(
        file_texts,
        query,
        max_parse_length=file_preprocess_config.max_parse_length,
        prompt_max_token_length=file_preprocess_config.prompt_max_token_length,
    )


# ---------------------------------------------------------------------------
# Cleanup: delete MinIO caches + soft-delete PG records
# ---------------------------------------------------------------------------


def cleanup_conversation_files(conversation_id: str) -> None:
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
