from consts.error_code import ErrorCode
from consts.exceptions import AppException
from utils.knowledge_ingestion_errors import classify_ingestion_exception


def test_disk_watermark_is_a_non_retryable_storage_write_block():
    classified = classify_ingestion_exception(
        Exception(
            "cluster_block_exception: disk usage exceeded flood-stage watermark; "
            "index has read-only-allow-delete block"
        ),
        "FORWARD",
    )

    assert classified.error_code == ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value
    assert classified.error_message is None
    assert classified.retryable is False


def test_known_code_never_persists_the_raw_exception_message():
    classified = classify_ingestion_exception(
        AppException(ErrorCode.TENANT_RESOURCE_EXCEEDED, "internal quota details"),
        "QUOTA",
    )

    assert classified.error_code == ErrorCode.TENANT_RESOURCE_EXCEEDED.value
    assert classified.error_message is None


def test_unknown_exception_keeps_only_a_bounded_raw_summary():
    raw_message = "unclassified ingestion error " * 30
    classified = classify_ingestion_exception(RuntimeError(raw_message), "PROCESS")

    assert classified.error_code is None
    assert classified.error_message == raw_message[:500]


def test_storage_and_task_submission_get_stable_service_codes():
    storage = classify_ingestion_exception(RuntimeError("db unavailable"), "STORAGE_COMMIT")
    submit = classify_ingestion_exception(RuntimeError("broker failed"), "TASK_SUBMIT")

    assert storage.error_code == ErrorCode.KNOWLEDGE_STORAGE_COMMIT_FAILED.value
    assert storage.error_message is None
    assert submit.error_code == ErrorCode.KNOWLEDGE_TASK_SUBMIT_FAILED.value
    assert submit.error_message is None


def test_structured_existing_ingestion_code_is_preserved():
    classified = classify_ingestion_exception(
        {"detail": {"error_code": "es_dim_mismatch"}, "message": "internal ES payload"},
        "FORWARD",
    )

    assert classified.error_code == "es_dim_mismatch"
    assert classified.error_message is None


def test_explicit_upstream_code_is_preserved_even_without_local_translation():
    classified = classify_ingestion_exception(
        {"code": "UPSTREAM_STORAGE_42", "message": "internal upstream detail"},
        "FORWARD",
    )

    assert classified.error_code == "UPSTREAM_STORAGE_42"
    assert classified.error_message is None


def test_json_encoded_exception_code_is_preserved():
    classified = classify_ingestion_exception(
        Exception('{"error_code":"es_bulk_failed", "message":"bulk request failed"}'),
        "FORWARD",
    )

    assert classified.error_code == "es_bulk_failed"
    assert classified.error_message is None


def test_long_nested_exception_code_is_preserved_before_message_truncation():
    payload = {
        "message": (
            "Unexpected error when indexing documents: "
            + '{"message":"ElasticSearch service returned HTTP 500",'
            + '"index_name":"index-with-a-long-name-for-real-forwarding",'
            + '"source":"knowledge_base/20260825183619_1262461a83c84d9f95ebd222cb656159.txt",'
            + '"original_filename":"a-very-long-filename.txt",'
            + '"error_code":"060106"}'
        ),
        "index_name": "index-with-a-long-name-for-real-forwarding",
        "task_name": "forward",
        "source": "knowledge_base/20260825183619_1262461a83c84d9f95ebd222cb656159.txt",
        "original_filename": "a-very-long-filename.txt",
        "error_code": "060106",
    }
    exception = Exception(__import__("json").dumps(payload, ensure_ascii=False))

    classified = classify_ingestion_exception(exception, "FORWARD")

    assert len(str(exception)) > 500
    assert classified.error_code == ErrorCode.KNOWLEDGE_INDEX_WRITE_BLOCKED.value
    assert classified.error_message is None
    assert classified.retryable is False
